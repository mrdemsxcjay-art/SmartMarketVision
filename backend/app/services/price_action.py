"""Price-action service (Phase 3).

Glue between the pure engine (:mod:`app.price_action.engine`) and the running
application:

* runs the price-action engine on the closed candles of a series, giving it the
  current *chartist* state of the same pair/timeframe so it can reuse the real
  levels and the confirmed breakouts (no second level or breakout engine);
* publishes PRICE_ACTION_DETECTED / CONFIRMED / INVALIDATED / EXPIRED and the
  distinct FAILED_BREAKOUT event on the **same** event bus as Phase 1 and 2
  (WebSocket + SSE);
* persists detections (one row per pattern+candle, updated in place) and events;
* exposes the active list, the structure states, the confluence groups and the
  centralised parameters.

No order, no broker, no position, no trading recommendation: this service only
observes and explains.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.db.repository import DetectionRepository, EventRepository
from app.logging_conf import get_logger
from app.price_action.engine import ENGINE_NAME, LifecycleEvent, PriceActionEngine, SeriesResult
from app.price_action.params import PriceActionParams
from app.price_action.params import params as default_params
from app.schemas.events import (
    DetectionsResponse,
    DetectorStatus,
    EventType,
    MarketEvent,
    PatternDetection,
)
from app.schemas.market import CandleSeries
from app.services.events import EventBus, event_bus

logger = get_logger(__name__)


class PriceActionService:
    def __init__(
        self,
        engine: PriceActionEngine | None = None,
        bus: EventBus | None = None,
        detection_repository: DetectionRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self.engine = engine or PriceActionEngine(default_params)
        self.bus = bus or event_bus
        self.detections_repo = detection_repository or DetectionRepository()
        self.events_repo = event_repository or EventRepository()

        self.runs = 0
        self.bars_analysed = 0
        self.last_run_ms: float | None = None
        self.last_run_at: datetime | None = None
        self.events_published = 0
        self.errors: list[str] = []
        #: last run per series, for the API and the health report
        self.last_results: dict[str, dict[str, object]] = {}

    # --------------------------------------------------------------- running
    def analyse(
        self,
        series: CandleSeries,
        chartist: list[PatternDetection] | None = None,
        *,
        publish: bool = True,
    ) -> SeriesResult:
        """Analyse one series and push whatever the engine found."""
        started = time.perf_counter()
        try:
            result = self.engine.analyse(series, chartist=chartist)
        except Exception as exc:  # a broken detector must never kill the scanner
            message = f"{series.symbol} {series.timeframe.value}: {type(exc).__name__} - {exc}"
            logger.exception("Price-action engine failed on %s", message)
            self.errors = ([message] + self.errors)[:10]
            return SeriesResult(
                symbol=series.symbol,
                timeframe=series.timeframe.value,
                bars_analyzed=0,
                candidates=0,
                notes=[message],
            )

        events = self.engine.commit(result)
        self.runs += 1
        self.bars_analysed += result.bars_analyzed
        self.last_run_ms = round((time.perf_counter() - started) * 1000, 2)
        self.last_run_at = datetime.now(tz=timezone.utc)
        self.last_results[f"{result.symbol} {result.timeframe}"] = {
            "bars": result.bars_analyzed,
            "candidates": result.candidates,
            "detections": len(result.detections),
            "structure": result.structure,
            "context": result.context,
            "notes": result.notes,
            "duration_ms": result.duration_ms,
            "at": self.last_run_at.isoformat(),
        }

        self._persist(result.detections)
        if publish:
            self._publish(events, series)
        return result

    # ------------------------------------------------------------- internals
    def _persist(self, detections: list[PatternDetection]) -> None:
        if not detections:
            return
        try:
            self.detections_repo.save_many(detections)
        except Exception as exc:  # persistence is best effort, but never silent
            logger.error("Could not persist %s price-action detections: %s", len(detections), exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, events: list[LifecycleEvent], series: CandleSeries) -> None:
        for event in events:
            try:
                event_type = EventType(event.event_type)
            except ValueError:  # pragma: no cover - guard against a typo in the engine
                logger.error("Unknown price-action event type %s", event.event_type)
                continue

            detection = event.detection
            metadata = {
                "detection": detection.model_dump(mode="json"),
                "previous_status": event.previous_status.value if event.previous_status else None,
                "pattern": detection.pattern,
                "direction": detection.direction.value,
                "status": detection.status.value,
                "confidence": detection.confidence,
                "dedup_key": detection.dedup_key,
                "category": detection.category.value,
                "level_context": detection.evidence_points.get("level_context"),
                "data_state": series.data_state.value,
                "provider": series.provider,
                "trading_signal": False,
            }
            if event.extra:
                metadata.update(event.extra)

            market_event = MarketEvent(
                event_type=event_type,
                symbol=detection.symbol,
                timeframe=detection.timeframe,
                price=_reference_price(detection),
                metadata=metadata,
                source=ENGINE_NAME,
            )
            self.bus.publish_nowait(market_event)
            self.events_published += 1
            try:
                self.events_repo.save(market_event)
            except Exception as exc:  # pragma: no cover - best effort
                logger.error("Could not persist price-action event: %s", exc)

    # --------------------------------------------------------------- reading
    def tracked(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.all(symbol=symbol, timeframe=timeframe)

    def active(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.active(symbol=symbol, timeframe=timeframe)

    def structure(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.structure(symbol=symbol, timeframe=timeframe)

    def response(self, symbol: str | None = None, timeframe: str | None = None) -> DetectionsResponse:
        tracked = self.tracked(symbol, timeframe)
        active = [d for d in tracked if d.status.value == "DETECTED"]
        counts: dict[str, int] = {}
        for detection in tracked:
            counts[detection.status.value] = counts.get(detection.status.value, 0) + 1
        return DetectionsResponse(
            status="ACTIVE PRICE ACTION" if active else "NO ACTIVE PRICE ACTION",
            detections=tracked,
            counts=counts,
            engines=self.engines(),
            stats=self.stats(),
            message=(
                "Price-action engine (Phase 3) : bougies cloturees uniquement, criteres explicites, "
                "aucun signal de trading, aucun ordre."
            ),
        )

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        pattern: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        return self.detections_repo.history(
            limit=limit, symbol=symbol, timeframe=timeframe, pattern=pattern, status=status
        )

    def confluence(self, symbol: str | None = None, timeframe: str | None = None, chartist=None) -> list[dict]:
        groups = self.engine.confluence_groups(
            chartist=chartist, symbol=symbol, timeframe=timeframe
        )
        return [group.as_dict() for group in groups]

    def engines(self) -> dict[str, DetectorStatus]:
        return {
            ENGINE_NAME: DetectorStatus.ENABLED if self.engine.params.enabled else DetectorStatus.DISABLED,
            "SMC_ICT_ENGINE": DetectorStatus.ENABLED,
        }

    @property
    def params(self) -> PriceActionParams:
        return self.engine.params

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
                "persisted": _safe_count(self.detections_repo.count),
                "series": len(self.last_results),
                "errors": self.errors[:5],
            }
        )
        return stats


def _reference_price(detection: PatternDetection) -> float | None:
    """A real price for the event envelope, read from the detection's own levels."""
    preferred = ("TRIGGER", "PATTERN_HIGH", "BOX_HIGH", "IMPULSE_END", "LEVEL", "BREAKOUT_LEVEL")
    for name in preferred:
        for level in detection.drawing.levels:
            if level.label == name:
                return float(level.price)
    points = detection.evidence_points.get("pivots") or {}
    for pivot in points.values():
        if isinstance(pivot, dict) and pivot.get("price") is not None:
            return float(pivot["price"])
    if detection.coordinates:
        return float(detection.coordinates[-1].price)
    return None


def _safe_count(callable_) -> int:  # pragma: no cover - guard for a locked database
    try:
        return int(callable_())
    except Exception as exc:
        logger.error("Price-action detection count failed: %s", exc)
        return -1


#: application-wide instance (the container may replace it in tests)
price_action_service = PriceActionService()
