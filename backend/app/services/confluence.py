"""Confluence service (Phase 5) - glue between the engine and the application.

Same shape as the Phase 3 / Phase 4 services:

* runs :class:`~app.confluence.engine.ConfluenceEngine` on the closed candles of a
  series, from the detections the three existing engines already published (the
  engines themselves are untouched);
* persists the groups (one row per confluence, updated in place) in ``confluences``;
* publishes CONFLUENCE_DETECTED / CONFLUENCE_UPDATED / CONFLUENCE_CONTRADICTED /
  CONFLUENCE_EXPIRED on the **same** event bus as phases 1 to 4, with
  ``trading_signal: False`` and no instruction of any kind;
* exposes the current confluences, the history, the explicable parameters and the
  statistics to the API and the dashboard.

A confluence is a description of the market, never a recommendation: the service
has no order, broker or position surface.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.confluence.engine import OBSERVED_STATES, ConfluenceEngine, LifecycleEvent, SeriesConfluence
from app.confluence.params import ConfluenceParams
from app.confluence.params import params as default_params
from app.db.repository import ConfluenceRepository, EventRepository
from app.logging_conf import get_logger
from app.schemas.events import DetectorStatus, EventType, MarketEvent, PatternDetection
from app.schemas.market import CandleSeries
from app.services.events import EventBus, event_bus

logger = get_logger(__name__)


class ConfluenceService:
    def __init__(
        self,
        engine: ConfluenceEngine | None = None,
        bus: EventBus | None = None,
        repository: ConfluenceRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self.engine = engine or ConfluenceEngine(default_params)
        self.bus = bus or event_bus
        self.repository = repository or ConfluenceRepository()
        self.events_repo = event_repository or EventRepository()

        self.runs = 0
        self.bars_analysed = 0
        self.last_run_ms: float | None = None
        self.last_run_at: datetime | None = None
        self.events_published = 0
        self.errors: list[str] = []
        self.last_results: dict[str, dict[str, object]] = {}

    # ---------------------------------------------------------------- running
    def analyse(
        self,
        series: CandleSeries,
        detections: list[PatternDetection],
        *,
        context: dict[str, list[PatternDetection]] | None = None,
        publish: bool = True,
    ) -> SeriesConfluence:
        """Analyse one series from the detections of the three engines."""
        started = time.perf_counter()
        try:
            result = self.engine.analyse(series, detections, context=context)
        except Exception as exc:  # a broken run must never kill the scanner
            message = f"{series.symbol} {series.timeframe.value}: {type(exc).__name__} - {exc}"
            logger.exception("Confluence engine failed on %s", message)
            self.errors = ([message] + self.errors)[:10]
            return SeriesConfluence(symbol=series.symbol, timeframe=series.timeframe.value)

        events = self.engine.commit(result)
        self.runs += 1
        self.bars_analysed += result.bars_analyzed
        self.last_run_ms = round((time.perf_counter() - started) * 1000, 2)
        self.last_run_at = datetime.now(tz=timezone.utc)
        key = f"{result.symbol} {result.timeframe}"
        self.last_results[key] = {
            "bars": result.bars_analyzed,
            "events_considered": result.events_considered,
            "events_aligned": result.events_aligned,
            "groups": len(result.groups),
            "states": [group.state for group in result.groups],
            "notes": result.notes,
            "duration_ms": result.duration_ms,
            "at": self.last_run_at.isoformat(),
        }

        self._persist(result.groups)
        if publish:
            self._publish(events, result)
        return result

    # -------------------------------------------------------------- internals
    def _persist(self, groups) -> None:
        if not groups:
            return
        try:
            self.repository.save_many(list(groups))
        except Exception as exc:  # persistence is best effort, but never silent
            logger.error("Could not persist %s confluence(s): %s", len(groups), exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, events: list[LifecycleEvent], result: SeriesConfluence) -> None:
        for event in events:
            try:
                event_type = EventType(event.event_type)
            except ValueError:  # pragma: no cover - guard against a typo
                logger.error("Unknown confluence event type %s", event.event_type)
                continue
            group = event.group
            metadata = {
                "confluence": group.compact(),
                "confluence_id": group.id,
                "previous_state": event.previous_state,
                "state": group.state,
                "score": group.score,
                "max_score": group.max_score,
                "dimensions": group.dimensions,
                "events": [source.id for source in group.events],
                "event_types": [source.type for source in group.events],
                "why": group.why,
                "against": group.against,
                "multi_timeframe": group.multi_timeframe,
                "timeframe": group.timeframe,
                "trading_signal": False,
                "note": (
                    "Confluence descriptive : plusieurs lectures concordent, "
                    "aucune recommandation, aucun ordre."
                ),
            }
            market_event = MarketEvent(
                event_type=event_type,
                symbol=group.symbol,
                timeframe=group.timeframe,
                price=group.reference_price,
                metadata=metadata,
                source=ConfluenceEngine.ENGINE_NAME,
            )
            self.bus.publish_nowait(market_event)
            self.events_published += 1
            try:
                self.events_repo.save(market_event)
            except Exception as exc:  # pragma: no cover - best effort
                logger.error("Could not persist confluence event: %s", exc)

    # ---------------------------------------------------------------- reading
    def observed(self, symbol: str | None = None, timeframe: str | None = None):
        return self.engine.observed(symbol, timeframe)

    def tracked(self, symbol: str | None = None, timeframe: str | None = None):
        return self.engine.all(symbol, timeframe)

    def get(self, group_id: str):
        group = self.engine.get(group_id)
        if group is not None:
            return group
        stored = self.repository.get(group_id)
        return stored if stored else None

    def strongest(self, symbol: str | None = None, timeframe: str | None = None):
        return self.engine.strongest(symbol, timeframe)

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        state: str | None = None,
        direction: str | None = None,
    ) -> list[dict]:
        return self.repository.history(
            limit=limit, symbol=symbol, timeframe=timeframe, state=state, direction=direction
        )

    def overview(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        """Compact market-overview block for the dashboard header."""
        groups = self.observed(symbol, timeframe)
        strongest = groups[0] if groups else None
        tracked = self.tracked(symbol, timeframe)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "state": strongest.state if strongest else "NO_CONFLUENCE",
            "direction": strongest.direction if strongest else "NEUTRAL",
            "score": strongest.score if strongest else 0.0,
            "max_score": self.engine.params.max_score(),
            "confluence_id": strongest.id if strongest else None,
            "observed": len(groups),
            "tracked": len(tracked),
            "contradicted": sum(1 for group in tracked if group.state == "CONTRADICTED"),
        }

    def params(self) -> ConfluenceParams:
        return self.engine.params

    def update_params(self, overrides: dict) -> list[str]:
        applied = self.engine.params.apply_overrides(overrides)
        logger.info("Confluence parameters updated: %s", applied)
        return applied

    def engines(self) -> dict[str, DetectorStatus]:
        return {
            ConfluenceEngine.ENGINE_NAME: DetectorStatus.ENABLED
            if self.engine.params.enabled
            else DetectorStatus.DISABLED
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
                "persisted": _safe(self.repository.count),
                "persisted_by_state": _safe(self.repository.count_by_state, {}),
                "series": len(self.last_results),
                "errors": self.errors[:5],
            }
        )
        return stats

    def snapshot(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        """Compact state sent to one connection on connect (reload-free dashboard)."""
        groups = self.tracked(symbol, timeframe)
        return {
            "count": len(groups),
            "observed": sum(1 for group in groups if group.state in OBSERVED_STATES),
            "by_state": _count_by(groups, "state"),
            "by_direction": _count_by(groups, "direction"),
            "top": [group.compact() for group in self.observed(symbol, timeframe)[:3]],
            "symbol": symbol,
            "timeframe": timeframe,
        }


def _count_by(groups, attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in groups:
        value = str(getattr(group, attribute, "?"))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _safe(callable_, default=-1):
    try:
        return callable_()
    except Exception as exc:  # pragma: no cover - guard for a locked database
        logger.error("Confluence count failed: %s", exc)
        return default


#: application-wide instance (the container may replace it in tests)
confluence_service = ConfluenceService()
