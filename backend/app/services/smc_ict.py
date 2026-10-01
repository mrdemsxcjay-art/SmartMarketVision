"""SMC / ICT service (Phase 4).

Glue between the pure engine (:mod:`app.smc_ict.engine`) and the running
application - deliberately the same shape as the price-action service:

* runs the engine on the closed candles of a series;
* publishes SMC_DETECTED / SMC_CONFIRMED / SMC_MITIGATED / SMC_INVALIDATED /
  SMC_FILLED / SMC_EXPIRED on the **same** event bus as phases 1 to 3 (WebSocket
  + SSE), with ``trading_signal: False`` in every payload;
* persists detections (one row per object + candle, updated in place) and events;
* exposes the active objects, the SMC confluence groups, the centralised
  parameters and the statistics.

No order, no broker, no position, no recommendation: this service observes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from app.db.repository import DetectionRepository, EventRepository
from app.logging_conf import get_logger
from app.schemas.events import (
    DetectionStatus,
    DetectionsResponse,
    DetectorStatus,
    EventType,
    MarketEvent,
    PatternDetection,
)
from app.schemas.market import CandleSeries
from app.services.events import EventBus, event_bus
from app.smc_ict.engine import ENGINE_NAME, LifecycleEvent, SeriesResult, SmcIctEngine
from app.smc_ict.params import SmcIctParams
from app.smc_ict.params import params as default_params

logger = get_logger(__name__)


class SmcIctService:
    def __init__(
        self,
        engine: SmcIctEngine | None = None,
        bus: EventBus | None = None,
        detection_repository: DetectionRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self.engine = engine or SmcIctEngine(default_params)
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
        #: last SMC confluence groups per series (descriptive only)
        self.last_confluence: dict[str, list[dict[str, object]]] = {}

    # --------------------------------------------------------------- running
    def analyse(self, series: CandleSeries, *, publish: bool = True) -> SeriesResult:
        """Analyse one series and push whatever the engine found."""
        started = time.perf_counter()
        try:
            result = self.engine.analyse(series)
        except Exception as exc:  # a broken detector must never kill the scanner
            message = f"{series.symbol} {series.timeframe.value}: {type(exc).__name__} - {exc}"
            logger.exception("SMC/ICT engine failed on %s", message)
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
        key = f"{result.symbol} {result.timeframe}"
        self.last_results[key] = {
            "bars": result.bars_analyzed,
            "candidates": result.candidates,
            "detections": len(result.detections),
            "structure": result.structure,
            "context": result.context,
            "confluence": len(result.confluence),
            "notes": result.notes,
            "warnings": result.warnings,
            "duration_ms": result.duration_ms,
            "at": self.last_run_at.isoformat(),
        }
        self.last_confluence[key] = result.confluence

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
            logger.error("Could not persist %s SMC/ICT detections: %s", len(detections), exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, events: list[LifecycleEvent], series: CandleSeries) -> None:
        for event in events:
            try:
                event_type = EventType(event.event_type)
            except ValueError:  # pragma: no cover - guard against a typo in the engine
                logger.error("Unknown SMC/ICT event type %s", event.event_type)
                continue

            detection = event.detection
            metadata = {
                "detection": detection.model_dump(mode="json"),
                "previous_status": event.previous_status.value if event.previous_status else None,
                "pattern": detection.pattern,
                "family": detection.parameters.get("family"),
                "direction": detection.direction.value,
                "status": detection.status.value,
                "confidence": detection.confidence,
                "dedup_key": detection.dedup_key,
                "state": detection.parameters.get("state"),
                "estimate": bool(detection.evidence_points.get("estimate", False)),
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
                logger.error("Could not persist SMC/ICT event: %s", exc)

    # --------------------------------------------------------------- reading
    def tracked(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.all(symbol=symbol, timeframe=timeframe)

    def active(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.active(symbol=symbol, timeframe=timeframe)

    def structure(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return self.engine.structure(symbol=symbol, timeframe=timeframe)

    def response(self, symbol: str | None = None, timeframe: str | None = None) -> DetectionsResponse:
        tracked = self.tracked(symbol, timeframe)
        active = [d for d in tracked if d.status in (DetectionStatus.DETECTED, DetectionStatus.ACTIVE)]
        counts: dict[str, int] = {}
        for detection in tracked:
            counts[detection.status.value] = counts.get(detection.status.value, 0) + 1
        return DetectionsResponse(
            status="ACTIVE SMC ICT" if active else "NO ACTIVE SMC ICT",
            detections=tracked,
            counts=counts,
            engines=self.engines(),
            stats=self.stats(),
            message=(
                "Moteur SMC/ICT (Phase 4) : bougies cloturees uniquement, criteres explicites, "
                "liquidite toujours estimee, aucun signal de trading, aucun ordre."
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
            limit=limit,
            symbol=symbol,
            timeframe=timeframe,
            pattern=pattern,
            status=status,
            category="SMC_ICT",
        )

    def confluence(self, symbol: str | None = None, timeframe: str | None = None) -> list[dict]:
        """Last SMC confluence groups (descriptive: never a score, never a signal)."""
        items: list[dict] = []
        for key, groups in self.last_confluence.items():
            if symbol and not key.upper().startswith(symbol.upper()):
                continue
            if timeframe and not key.upper().endswith(timeframe.upper()):
                continue
            items.extend(groups)
        items.sort(key=lambda group: int(group.get("to_index", 0)), reverse=True)
        return items

    def engines(self) -> dict[str, DetectorStatus]:
        return {
            ENGINE_NAME: DetectorStatus.ENABLED if self.engine.params.enabled else DetectorStatus.DISABLED
        }

    @property
    def params(self) -> SmcIctParams:
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

    def snapshot(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        """Compact state sent to one connection on connect (reload-free dashboard)."""
        tracked = self.tracked(symbol, timeframe)
        counts: dict[str, int] = {}
        families: dict[str, int] = {}
        for detection in tracked:
            counts[detection.pattern] = counts.get(detection.pattern, 0) + 1
            family = str(detection.parameters.get("family", "?"))
            families[family] = families.get(family, 0) + 1
        return {
            "count": len(tracked),
            "by_pattern": counts,
            "by_family": families,
            "confluence": len(self.confluence(symbol, timeframe)),
            "symbol": symbol,
            "timeframe": timeframe,
        }


def _reference_price(detection: PatternDetection) -> float | None:
    """A real price for the event envelope, read from the detection's own levels."""
    preferred = (
        "BREAK_CLOSE",
        "BROKEN_SWING",
        "LIQUIDITY_LEVEL",
        "REENTRY",
        "UPPER_PRICE",
        "LOWER_PRICE",
        "ZONE_HIGH",
        "ZONE_LOW",
        "POOL_LEVEL",
        "LEVEL",
        "EQUILIBRIUM",
    )
    for name in preferred:
        for level in detection.drawing.levels:
            if level.label == name:
                return float(level.price)
    if detection.coordinates:
        return float(detection.coordinates[-1].price)
    return None


def _safe_count(callable_) -> int:  # pragma: no cover - guard for a locked database
    try:
        return int(callable_())
    except Exception as exc:
        logger.error("SMC/ICT detection count failed: %s", exc)
        return -1


#: application-wide instance (the container may replace it in tests)
smc_ict_service = SmcIctService()
