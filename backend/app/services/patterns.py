"""Chart pattern service.

Glue between the pure engine (:mod:`app.patterns.engine`) and the running
application:

* runs the engine on the closed candles of a series;
* publishes the lifecycle events (PATTERN_DETECTED / BREAKOUT_DETECTED /
  PATTERN_CONFIRMED / PATTERN_INVALIDATED / PATTERN_EXPIRED / RETEST_DETECTED)
  on the event bus, which feeds WebSocket and SSE;
* persists the events and the detections (one row per formation, updated in
  place) so the history can be replayed and back-tested;
* exposes the active list, the history and the parameter snapshot to the API.

Nothing here invents data: an engine error is logged and reported, never hidden.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.db.repository import DetectionRepository, EventRepository
from app.logging_conf import get_logger
from app.patterns.engine import ChartPatternEngine, LifecycleEvent, SeriesResult
from app.patterns.params import PatternParams, params as default_params
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

ENGINE_NAME = "CHART_PATTERN_ENGINE"


class PatternService:
    def __init__(
        self,
        engine: ChartPatternEngine | None = None,
        bus: EventBus | None = None,
        detection_repository: DetectionRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self.engine = engine or ChartPatternEngine(default_params)
        self.bus = bus or event_bus
        self.detections_repo = detection_repository or DetectionRepository()
        self.events_repo = event_repository or EventRepository()

        self.runs = 0
        self.bars_analysed = 0
        self.last_run_ms: float | None = None
        self.last_run_at: datetime | None = None
        self.events_published = 0
        self.errors: list[str] = []

    # ------------------------------------------------------------- running
    def analyse(self, series: CandleSeries, *, publish: bool = True) -> SeriesResult:
        """Analyse one series and push whatever the engine found."""
        started = time.perf_counter()
        try:
            result = self.engine.analyse(series)
        except Exception as exc:  # a detector crash must never kill the scanner
            message = f"{series.symbol} {series.timeframe.value}: {type(exc).__name__} - {exc}"
            logger.exception("Pattern engine failed on %s", message)
            self.errors = ([message] + self.errors)[:10]
            return SeriesResult(
                symbol=series.symbol,
                timeframe=series.timeframe.value,
                bars_analyzed=0,
                pivots=0,
                candidates=0,
                notes=[message],
            )

        events = self.engine.commit(result)
        self.runs += 1
        self.bars_analysed += result.bars_analyzed
        self.last_run_ms = round((time.perf_counter() - started) * 1000, 2)
        self.last_run_at = datetime.now(tz=timezone.utc)

        self._persist(result.detections)
        if publish:
            self._publish(events, series)
        return result

    # ----------------------------------------------------------- internals
    def _persist(self, detections: list[PatternDetection]) -> None:
        if not detections:
            return
        try:
            self.detections_repo.save_many(detections)
        except Exception as exc:  # persistence is best effort, but never silent
            logger.error("Could not persist %s detections: %s", len(detections), exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, events: list[LifecycleEvent], series: CandleSeries) -> None:
        for event in events:
            try:
                event_type = EventType(event.event_type)
            except ValueError:  # pragma: no cover - guard against a typo in the engine
                logger.error("Unknown pattern event type %s", event.event_type)
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
                "data_state": series.data_state.value,
                "provider": series.provider,
            }
            if event.breakout is not None:
                metadata["breakout"] = event.breakout.model_dump(mode="json")
            if event.retest is not None:
                metadata["retest"] = event.retest.model_dump(mode="json")

            price = detection.breakout.breakout_price if detection.breakout else None
            market_event = MarketEvent(
                event_type=event_type,
                symbol=detection.symbol,
                timeframe=detection.timeframe,
                price=price,
                metadata=metadata,
                source=ENGINE_NAME,
            )
            self.bus.publish_nowait(market_event)
            self.events_published += 1
            try:
                self.events_repo.save(market_event)
            except Exception as exc:  # pragma: no cover - best effort
                logger.error("Could not persist pattern event: %s", exc)

    # ------------------------------------------------------------- reading
    def active(
        self, symbol: str | None = None, timeframe: str | None = None
    ) -> list[PatternDetection]:
        return self.engine.active(symbol=symbol, timeframe=timeframe)

    def tracked(
        self, symbol: str | None = None, timeframe: str | None = None
    ) -> list[PatternDetection]:
        return self.engine.all(symbol=symbol, timeframe=timeframe)

    def response(self, symbol: str | None = None, timeframe: str | None = None) -> DetectionsResponse:
        active = self.active(symbol, timeframe)
        tracked = self.tracked(symbol, timeframe)
        counts: dict[str, int] = {}
        for detection in tracked:
            counts[detection.status.value] = counts.get(detection.status.value, 0) + 1
        return DetectionsResponse(
            status="ACTIVE DETECTIONS" if active else "NO ACTIVE DETECTION",
            detections=tracked,
            counts=counts,
            engines=self.engines(),
            stats=self.stats(),
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

    def engines(self) -> dict[str, DetectorStatus]:
        return {
            ENGINE_NAME: DetectorStatus.ENABLED if self.engine.params.enabled else DetectorStatus.DISABLED,
            "PRICE_ACTION_ENGINE": DetectorStatus.ENABLED,
            "SMC_ICT_ENGINE": DetectorStatus.ENABLED,
        }

    @property
    def params(self) -> PatternParams:
        return self.engine.params

    def stats(self) -> dict:
        stats = self.engine.stats()
        stats.update(
            {
                "engine": ENGINE_NAME,
                "enabled": self.engine.params.enabled,
                "runs": self.runs,
                "bars_analysed": self.bars_analysed,
                "last_run_ms": self.last_run_ms,
                "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
                "events_published": self.events_published,
                "persisted": _safe_count(self.detections_repo.count),
                "errors": self.errors[:5],
            }
        )
        return stats


def _safe_count(callable_) -> int:  # pragma: no cover - guard for a locked database
    try:
        return int(callable_())
    except Exception as exc:
        logger.error("Detection count failed: %s", exc)
        return -1


#: application-wide instance (the container may replace it in tests)
pattern_service = PatternService()
