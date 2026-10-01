"""Opportunity service (Phase 6) - glue between the engine and the application.

* runs the opportunity engine on the confluences of one series;
* persists the opportunities in ``opportunities`` (one row per observation,
  updated in place);
* publishes OPPORTUNITY_* on the **same** event bus as phases 1 to 5;
* hands the notifiable observations to the Telegram outbox **without ever waiting
  for it** (Phase 8 owns the delivery);
* exposes the current observations, the history, the parameters and the stats.

``BUY`` / ``SELL`` here are analytical directions. The service has no order, no
broker and no position capability, and it never will.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.confluence.models import ConfluenceGroup, ConfluenceState
from app.db.repository import EventRepository, OpportunityRepository
from app.logging_conf import get_logger
from app.opportunities.engine import ENGINE_NAME, LifecycleEvent, OpportunityEngine, alert_id
from app.opportunities.models import Opportunity, OpportunityState, SeriesOpportunities
from app.opportunities.params import OpportunityParams
from app.opportunities.params import params as default_params
from app.schemas.events import DetectorStatus, EventType, MarketEvent
from app.schemas.market import CandleSeries
from app.services.events import EventBus, event_bus

logger = get_logger(__name__)


class OpportunityService:
    def __init__(
        self,
        engine: OpportunityEngine | None = None,
        bus: EventBus | None = None,
        repository: OpportunityRepository | None = None,
        event_repository: EventRepository | None = None,
        outbox=None,
    ) -> None:
        self.engine = engine or OpportunityEngine(default_params)
        self.bus = bus or event_bus
        self.repository = repository or OpportunityRepository()
        self.events_repo = event_repository or EventRepository()
        #: set by the container once the Telegram outbox exists (Phase 8). The
        #: scanner only ever *enqueues*: it never waits for a delivery.
        self.outbox = outbox

        self.runs = 0
        self.bars_analysed = 0
        self.last_run_ms: float | None = None
        self.last_run_at: datetime | None = None
        self.events_published = 0
        self.alerts_queued = 0
        self.alerts_skipped = 0
        self.errors: list[str] = []
        self.last_results: dict[str, dict[str, object]] = {}

    # ---------------------------------------------------------------- running
    def analyse(
        self,
        series: CandleSeries,
        confluences: list[ConfluenceGroup],
        *,
        publish: bool = True,
    ) -> SeriesOpportunities:
        started = time.perf_counter()
        try:
            result = self.engine.analyse(series, confluences)
        except Exception as exc:  # a broken run must never kill the scanner
            message = f"{series.symbol} {series.timeframe.value}: {type(exc).__name__} - {exc}"
            logger.exception("Opportunity engine failed on %s", message)
            self.errors = ([message] + self.errors)[:10]
            return SeriesOpportunities(symbol=series.symbol, timeframe=series.timeframe.value)

        events = self.engine.commit(result)
        self.runs += 1
        self.bars_analysed += result.bars_analyzed
        self.last_run_ms = round((time.perf_counter() - started) * 1000, 2)
        self.last_run_at = datetime.now(tz=timezone.utc)
        key = f"{result.symbol} {result.timeframe}"
        self.last_results[key] = {
            "confluences": result.confluences_considered,
            "opportunities": len(result.opportunities),
            "directions": [item.direction for item in result.opportunities],
            "states": [item.state for item in result.opportunities],
            "duration_ms": result.duration_ms,
            "at": self.last_run_at.isoformat(),
        }
        self._persist(result.opportunities)
        if publish:
            self._publish(events, series)
        return result

    # -------------------------------------------------------------- internals
    def _persist(self, opportunities: list[Opportunity]) -> None:
        if not opportunities:
            return
        try:
            self.repository.save_many(list(opportunities))
        except Exception as exc:
            logger.error("Could not persist %s opportunities: %s", len(opportunities), exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, events: list[LifecycleEvent], series: CandleSeries) -> None:
        for event in events:
            try:
                event_type = EventType(event.event_type)
            except ValueError:  # pragma: no cover - guard against a typo
                logger.error("Unknown opportunity event type %s", event.event_type)
                continue
            opportunity = event.opportunity
            metadata = {
                "opportunity": opportunity.as_dict(),
                "opportunity_id": opportunity.id,
                "previous_state": event.previous_state,
                "direction": opportunity.direction,
                "state": opportunity.state,
                "score": opportunity.score,
                "max_score": opportunity.max_score,
                "confluence_id": opportunity.confluence_id,
                "conditions": [condition.model_dump(mode="json") for condition in opportunity.conditions],
                "no_trade_reason": opportunity.no_trade_reason,
                "alert_id": alert_id(opportunity.alert_key or ""),
                "alert_key": opportunity.alert_key,
                "trading_signal": False,
                "order_execution": False,
                "note": (
                    "Direction analytique observee a partir des detections listees. "
                    "Ce systeme observe et alerte : rien n'est transmis a un tiers."
                ),
            }
            market_event = MarketEvent(
                event_type=event_type,
                symbol=opportunity.symbol,
                timeframe=opportunity.timeframe,
                price=opportunity.reference_price,
                metadata=metadata,
                source=ENGINE_NAME,
            )
            self.bus.publish_nowait(market_event)
            self.events_published += 1
            try:
                self.events_repo.save(market_event)
            except Exception as exc:  # pragma: no cover - best effort
                logger.error("Could not persist opportunity event: %s", exc)

            if event.notifiable:
                self._queue_alert(opportunity, event_type.value)

    def _queue_alert(self, opportunity: Opportunity, event_type: str) -> None:
        """Hand the alert to the outbox (never blocks the scanner)."""
        if self.outbox is None:
            return
        try:
            queued = self.outbox.enqueue_opportunity(opportunity, event_type)
        except Exception as exc:  # pragma: no cover - the outbox is best effort here
            logger.error("Could not queue the alert for %s: %s", opportunity.id, exc)
            self.errors = ([f"outbox: {exc}"] + self.errors)[:10]
            return
        if queued:
            self.alerts_queued += 1
        else:
            self.alerts_skipped += 1

    # ---------------------------------------------------------------- reading
    def tracked(self, symbol: str | None = None, timeframe: str | None = None) -> list[Opportunity]:
        return self.engine.all(symbol, timeframe)

    def named(self, symbol: str | None = None, timeframe: str | None = None) -> list[Opportunity]:
        return self.engine.named(symbol, timeframe)

    def get(self, opportunity_id: str):
        opportunity = self.engine.get(opportunity_id)
        if opportunity is not None:
            return opportunity
        stored = self.repository.get(opportunity_id)
        return stored if stored else None

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        direction: str | None = None,
        state: str | None = None,
    ) -> list[dict]:
        return self.repository.history(
            limit=limit, symbol=symbol, timeframe=timeframe, direction=direction, state=state
        )

    def overview(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        items = self.tracked(symbol, timeframe)
        primary = next((item for item in items if item.is_actionable_observation), None) or (items[0] if items else None)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": primary.direction if primary else "NO_TRADE",
            "state": primary.state if primary else None,
            "score": primary.score if primary else 0.0,
            "max_score": self.engine.params.max_score(),
            "opportunity_id": primary.id if primary else None,
            "confluence_id": primary.confluence_id if primary else None,
            "reference_price": primary.reference_price if primary else None,
            "no_trade_reason": primary.no_trade_reason if primary else None,
            "tracked": len(items),
            "named": sum(1 for item in items if item.is_actionable_observation),
        }

    def params(self) -> OpportunityParams:
        return self.engine.params

    def update_params(self, overrides: dict) -> list[str]:
        applied = self.engine.params.apply_overrides(overrides)
        logger.info("Opportunity parameters updated: %s", applied)
        return applied

    def engines(self) -> dict[str, DetectorStatus]:
        return {
            ENGINE_NAME: DetectorStatus.ENABLED if self.engine.params.enabled else DetectorStatus.DISABLED
        }

    def stats(self) -> dict:
        stats = self.engine.stats()
        stats.update(
            {
                "enabled": self.engine.params.enabled,
                "runs": self.runs,
                "bars_analysed": self.bars_analysed,
                "last_run_ms": self.last_run_ms,
                "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
                "events_published": self.events_published,
                "alerts_queued": self.alerts_queued,
                "alerts_skipped": self.alerts_skipped,
                "persisted": _safe(self.repository.count),
                "persisted_by_direction": _safe(self.repository.count_by_direction, {}),
                "persisted_by_state": _safe(self.repository.count_by_state, {}),
                "errors": self.errors[:5],
            }
        )
        return stats

    def snapshot(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        items = self.tracked(symbol, timeframe)
        return {
            "count": len(items),
            "named": sum(1 for item in items if item.is_actionable_observation),
            "by_direction": _count_by(items, "direction"),
            "by_state": _count_by(items, "state"),
            "top": [item.compact() for item in items[:3]],
            "symbol": symbol,
            "timeframe": timeframe,
        }


def _count_by(items, attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(getattr(item, attribute, "?"))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _safe(callable_, default=-1):
    try:
        return callable_()
    except Exception as exc:  # pragma: no cover - guard for a locked database
        logger.error("Opportunity count failed: %s", exc)
        return default


#: application-wide instance (the container may replace it in tests)
opportunity_service = OpportunityService()
