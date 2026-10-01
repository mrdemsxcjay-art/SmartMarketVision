"""SMC / ICT engine (Phase 4).

The engine is the only place that turns detector candidates into the **existing**
API contract: :class:`app.schemas.events.PatternDetection` with
``category = SMC_ICT`` and ``source_engine = SMC_ICT_ENGINE``. Nothing else in the
application needs to know that SMC/ICT exists beyond this module and its service.

What it does, in order:

1. builds the analysis context from the closed candles (reusing the Phase 1/2
   pivots and the Phase 1 candle metrics - no second pivot engine);
2. runs the detectors: structure (BOS/CHOCH/MSS), liquidity (equal levels, pool
   ESTIMATES, sweeps), gaps (FVG + mitigation), blocks (order blocks, and
   breakers derived from them), ranges (dealing range, premium/discount) and
   displacement;
3. anchors the long-lived objects (order blocks, breakers) on a wider structure
   history (``globals.structure_bars``) while the *events* stay on the live
   window (``globals.scan_bars``) - this is what keeps a tick cheap;
4. scores each candidate from its own explicit criteria
   (``app.patterns.confidence.score`` - never a guessed number);
5. keeps a registry keyed by the stable dedup key so the same object is never
   announced twice and a status change is published once.

No BUY/SELL/ENTRY/SL/TP, no order, no position, no global confluence engine:
the SMC confluence groups are descriptive lists, and ``trading_signal`` is frozen
to ``False`` in the parameters.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.logging_conf import get_logger
from app.patterns.confidence import score
from app.schemas.events import (
    ConfirmationInfo,
    DetectionCategory,
    DetectionDirection,
    DetectionSource,
    DetectionStatus,
    DrawingLevel,
    DrawingMarker,
    DrawingSpec,
    DrawingZone,
    InvalidationInfo,
    PatternCoordinate,
    PatternDetection,
    WatchedLevel,
)
from app.instruments import get_symbol_info, normalize_symbol
from app.schemas.market import CandleSeries
from app.smc_ict.context import build_context
from app.smc_ict.detectors.blocks import detect_breakers, detect_order_blocks
from app.smc_ict.detectors.confluence import detect_confluence
from app.smc_ict.detectors.gaps import detect_fvgs
from app.smc_ict.detectors.liquidity import (
    detect_equal_levels,
    detect_liquidity_pools,
    detect_liquidity_sweeps,
)
from app.smc_ict.detectors.ranges import (
    detect_dealing_range,
    detect_displacement,
    detect_premium_discount,
)
from app.smc_ict.detectors.structure import detect_structure
from app.smc_ict.models import ScanContext, SmcCandidate
from app.smc_ict.params import SmcIctParams
from app.smc_ict.params import params as default_params

logger = get_logger(__name__)

ENGINE_NAME = "SMC_ICT_ENGINE"

#: how many consecutive runs a detection may be absent before it is dropped
STALE_RUNS_BEFORE_DROP = 3

#: state reported by each pattern family (§20: only the relevant statuses)
STATUS_BY_PATTERN: dict[str, DetectionStatus] = {
    "BOS": DetectionStatus.CONFIRMED,
    "CHOCH": DetectionStatus.CONFIRMED,
    "MSS": DetectionStatus.CONFIRMED,
    "LIQUIDITY_SWEEP": DetectionStatus.CONFIRMED,
    "DISPLACEMENT": DetectionStatus.CONFIRMED,
    "EQUAL_HIGH": DetectionStatus.ACTIVE,
    "EQUAL_LOW": DetectionStatus.ACTIVE,
    "LIQUIDITY_POOL_ESTIMATE": DetectionStatus.ACTIVE,
    "DEALING_RANGE": DetectionStatus.ACTIVE,
    "PREMIUM": DetectionStatus.ACTIVE,
    "DISCOUNT": DetectionStatus.ACTIVE,
    "BULLISH_FVG": DetectionStatus.ACTIVE,
    "BEARISH_FVG": DetectionStatus.ACTIVE,
    "BULLISH_ORDER_BLOCK": DetectionStatus.ACTIVE,
    "BEARISH_ORDER_BLOCK": DetectionStatus.ACTIVE,
    "BREAKER_BLOCK": DetectionStatus.CONFIRMED,
}

#: mitigation states that override the family default
STATE_OVERRIDES = {
    "PARTIALLY_FILLED": DetectionStatus.MITIGATED,
    "FILLED": DetectionStatus.FILLED,
    "INVALIDATED": DetectionStatus.INVALIDATED,
    "MITIGATED": DetectionStatus.MITIGATED,
    "EXPIRED": DetectionStatus.EXPIRED,
    "CREATED": DetectionStatus.DETECTED,
}


@dataclass
class SeriesResult:
    """Outcome of one SMC/ICT run on one series."""

    symbol: str
    timeframe: str
    bars_analyzed: int
    candidates: int
    detections: list[PatternDetection] = field(default_factory=list)
    structure: list[str] = field(default_factory=list)
    context: dict[str, object] = field(default_factory=dict)
    confluence: list[dict[str, object]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class LifecycleEvent:
    """State transition to publish on the shared bus + persist."""

    event_type: str
    detection: PatternDetection
    previous_status: DetectionStatus | None = None
    extra: dict[str, object] = field(default_factory=dict)


def dedup_key(
    symbol: str,
    timeframe: str,
    pattern: str,
    trigger_time: int,
    source_time: int | None = None,
) -> str:
    """Stable identity: pair + timeframe + pattern + the real candles it is tied to.

    Two objects can share a trigger candle but never the same source candle, so
    the source bar is part of the payload: the same object always keeps the same
    id while its payload (state, coverage, touch count) is updated in place.
    """
    payload = f"{symbol}|{timeframe}|{pattern}|{trigger_time}"
    if source_time is not None:
        payload += f"|{source_time}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"smc_{digest}"


class SmcIctEngine:
    """Detects SMC/ICT objects on real OHLC series."""

    def __init__(self, params: SmcIctParams | None = None) -> None:
        self.params = params or default_params
        #: dedup_key -> PatternDetection
        self.registry: dict[str, PatternDetection] = {}
        self._stale_runs: dict[str, int] = {}
        self._previous_state: dict[str, DetectionStatus | None] = {}

    # -------------------------------------------------------------------- run
    def analyse(self, series: CandleSeries) -> SeriesResult:
        started = time.perf_counter()
        candles = series.candles
        timeframe = series.timeframe.value
        pip_size, digits = _pip_and_digits(series.symbol)

        if not self.params.enabled:
            return SeriesResult(
                symbol=normalize_symbol(series.symbol),
                timeframe=timeframe,
                bars_analyzed=len(candles),
                candidates=0,
                notes=["moteur SMC/ICT desactive par parametre"],
            )

        ctx = build_context(series, self.params, pip_size=pip_size, digits=digits)
        result = SeriesResult(
            symbol=normalize_symbol(series.symbol),
            timeframe=timeframe,
            bars_analyzed=len(candles),
            candidates=0,
        )
        if len(candles) < self.params.global_.min_bars_required:
            result.notes.append(
                f"{len(candles)} bougie(s) : minimum {self.params.global_.min_bars_required} requis, "
                "aucune analyse structurelle tentee"
            )
            result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return result

        candidates: list[SmcCandidate] = []
        # events: live window only (a tick must stay cheap)
        try:
            live_structure = detect_structure(ctx)
            candidates.extend(live_structure)
            # anchors: the same detector on a wider history, for long-lived objects
            history_structure = (
                live_structure
                if self.params.global_.structure_bars <= self.params.global_.scan_bars
                else detect_structure(ctx, self.params.global_.structure_bars)
            )
        except Exception as exc:  # a detector must never kill the scanner
            message = f"structure: {type(exc).__name__} - {exc}"
            logger.exception("SMC/ICT structure detector failed on %s %s", series.symbol, timeframe)
            result.warnings.append(message)
            live_structure, history_structure = [], []

        for name, function, args in (
            ("equal_levels", detect_equal_levels, ()),
            ("pools", detect_liquidity_pools, ()),
            ("sweeps", detect_liquidity_sweeps, ()),
            ("gaps", detect_fvgs, ()),
            ("displacement", detect_displacement, ()),
        ):
            try:
                candidates.extend(function(ctx, *args))
            except Exception as exc:
                message = f"{name}: {type(exc).__name__} - {exc}"
                logger.exception("SMC/ICT %s detector failed on %s %s", name, series.symbol, timeframe)
                result.warnings.append(message)

        try:
            blocks = detect_order_blocks(ctx, history_structure)
            candidates.extend(blocks)
            candidates.extend(detect_breakers(ctx, blocks, history_structure))
        except Exception as exc:
            message = f"blocks: {type(exc).__name__} - {exc}"
            logger.exception("SMC/ICT block detector failed on %s %s", series.symbol, timeframe)
            result.warnings.append(message)

        try:
            dealing_range = detect_dealing_range(ctx)
            if dealing_range is not None:
                candidates.append(dealing_range)
                zone = detect_premium_discount(ctx, dealing_range)
                if zone is not None:
                    candidates.append(zone)
        except Exception as exc:
            message = f"dealing_range: {type(exc).__name__} - {exc}"
            logger.exception("SMC/ICT dealing range failed on %s %s", series.symbol, timeframe)
            result.warnings.append(message)

        # hard cap, newest first, biggest families kept
        cap = self.params.global_.max_tracked
        candidates.sort(key=lambda c: (c.index, c.pattern), reverse=True)

        previous = {
            key: value
            for key, value in self.registry.items()
            if value.symbol == result.symbol and value.timeframe.value == timeframe
        }
        detections: list[PatternDetection] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = dedup_key(
                result.symbol,
                timeframe,
                candidate.pattern,
                candidate.time,
                ctx.metrics[candidate.source_from_index].time
                if candidate.source_from_index is not None
                and 0 <= candidate.source_from_index < len(ctx.metrics)
                else None,
            )
            if key in seen:
                continue
            seen.add(key)
            detection = self._to_detection(candidate, ctx, key)
            self._apply_state(detection, candidate, previous.get(key))
            detections.append(detection)
            if len(detections) >= cap:
                break

        result.candidates = len(candidates)
        result.detections = detections
        result.structure = sorted({c.pattern for c in candidates if c.family == "STRUCTURAL"})
        result.context = {
            "atr": round(ctx.atr, 8),
            "atr_pips": round(ctx.pips(ctx.atr), 2),
            "swings": len(ctx.swings),
            "pip_size": ctx.pip_size,
            "digits": ctx.digits,
            "bars": len(ctx.metrics),
            "min_size_1pip": round(ctx.min_size(1.0, 0.0), 8),
        }
        try:
            result.confluence = detect_confluence(ctx, candidates)
        except Exception as exc:
            result.warnings.append(f"confluence: {type(exc).__name__} - {exc}")
            logger.exception("SMC/ICT confluence failed on %s %s", series.symbol, timeframe)

        result.notes.append(
            "Analyse SMC/ICT : bougies cloturees uniquement, criteres explicites, "
            "aucun signal de trading, aucun ordre."
        )
        if not detections:
            result.notes.append("Aucun objet SMC/ICT retenu sur cette fenetre.")
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ------------------------------------------------------------ conversion
    def _to_detection(self, candidate: SmcCandidate, ctx: ScanContext, key: str) -> PatternDetection:
        confidence, factors = score(candidate.criteria)
        direction = {
            "BULLISH": DetectionDirection.BULLISH,
            "BEARISH": DetectionDirection.BEARISH,
            "NEUTRAL": DetectionDirection.NEUTRAL,
        }[candidate.direction]

        coordinates = [
            PatternCoordinate(
                time=ctx.metrics[index].time if 0 <= index < len(ctx.metrics) else candidate.time,
                price=round(price, 10),
                role=role,
                label=label,
            )
            for index, price, role, label in candidate.coordinates
        ]
        drawing = DrawingSpec(
            levels=[
                DrawingLevel(price=round(float(price), 10), label=name, kind=candidate.pattern)
                for name, price in candidate.levels.items()
            ],
            zones=[
                DrawingZone(
                    time_start=int(zone["time_start"]),
                    time_end=int(zone["time_end"]),
                    price_top=float(zone["price_top"]),
                    price_bottom=float(zone["price_bottom"]),
                    label=str(zone.get("label", candidate.pattern)),
                    kind=str(zone.get("kind", "SMC")),
                )
                for zone in candidate.zones
            ],
            markers=[
                DrawingMarker(
                    time=int(marker["time"]),
                    price=float(marker["price"]),
                    position=str(marker.get("position", "aboveBar")),
                    shape=str(marker.get("shape", "circle")),
                    label=str(marker.get("label", candidate.pattern)),
                    kind=str(marker.get("kind", "SMC")),
                )
                for marker in candidate.markers
            ],
        )

        status = STATUS_BY_PATTERN.get(candidate.pattern, DetectionStatus.DETECTED)
        state = candidate.measurements.get("state")
        if state is not None:
            status = STATE_OVERRIDES.get(str(state), status)

        trigger_level = _trigger_level(candidate)
        invalidation_level = _invalidation_level(candidate)
        confirmations = _confirmation_state(candidate)

        evidence_points = {
            "criteria": [
                {"criterion": criterion, "passed": passed, "weight": weight, "detail": detail}
                for criterion, passed, weight, detail in candidate.criteria
            ],
            "measurements": dict(candidate.measurements),
            "levels": dict(candidate.levels),
            "family": candidate.family,
            "source_index": candidate.source_from_index,
            "swings": [s.as_dict() for s in ctx.swings[-6:]],
            "atr": round(ctx.atr, 8),
            "atr_pips": round(ctx.pips(ctx.atr), 2),
            "pip_size": ctx.pip_size,
            "parameters_version": self.parameters_version,
            "object": _json_safe(candidate.extra),
            "estimate": bool(candidate.extra.get("estimate", False)),
            "trading_signal": False,
        }

        return PatternDetection(
            id=key,
            dedup_key=key,
            symbol=ctx.symbol,
            timeframe=series_timeframe(ctx.timeframe),
            timestamp=datetime.now(tz=timezone.utc),
            category=DetectionCategory.SMC_ICT,
            pattern=candidate.pattern,
            direction=direction,
            confidence=confidence,
            confidence_factors=factors,
            evidence=list(candidate.evidence),
            evidence_points=evidence_points,
            coordinates=coordinates,
            drawing=drawing,
            parameters={
                "engine": {
                    "window_bars": self.params.global_.window_bars,
                    "scan_bars": self.params.global_.scan_bars,
                    "structure_bars": self.params.global_.structure_bars,
                    "atr_period": self.params.global_.atr_period,
                    "pivot_left": self.params.global_.pivot_left,
                    "pivot_right": self.params.global_.pivot_right,
                },
                "family": candidate.family,
                "state": state,
                "parameters_version": self.parameters_version,
            },
            confirmation=ConfirmationInfo(
                confirmed=confirmations["confirmed"],
                level=confirmations["level"],
                level_type=confirmations["level_type"],
                breakout_time=confirmations["time"],
                breakout_price=confirmations["price"],
                breakout_candle_time=confirmations["time"],
                note=confirmations["note"],
            ),
            invalidation=InvalidationInfo(
                invalidated=bool(candidate.measurements.get("invalidated", False)),
                level=invalidation_level,
                level_type="SMC_INVALIDATION" if invalidation_level is not None else None,
                reason=(
                    f"statut {status.value} pour {candidate.pattern}"
                    if status
                    in (DetectionStatus.INVALIDATED, DetectionStatus.MITIGATED, DetectionStatus.FILLED)
                    else None
                ),
                invalidated_at=(
                    ctx.metrics[int(candidate.measurements["invalidation_index"])].time
                    if candidate.measurements.get("invalidation_index") is not None
                    else None
                ),
            ),
            status=status,
            watch_levels=(
                [
                    WatchedLevel(
                        level_type="SMC_TRIGGER",
                        price=round(trigger_level, 10),
                        direction=direction,
                        role="CONFIRMATION",
                    )
                ]
                if trigger_level is not None
                else []
            ),
            source_engine=DetectionSource.SMC_ICT_ENGINE,
            detected_at_bar_time=candidate.time,
            first_seen_at=datetime.now(tz=timezone.utc),
            last_updated_at=datetime.now(tz=timezone.utc),
            bars_in_window=len(ctx.metrics),
            notes=[
                f"Famille {candidate.family} - etat {state or status.value}",
                "SMC/ICT : objet descriptif, jamais une instruction de trading",
            ],
        )

    # -------------------------------------------------------------- lifecycle
    def _apply_state(
        self,
        detection: PatternDetection,
        candidate: SmcCandidate,
        existing: PatternDetection | None,
    ) -> None:
        """Carry over the first-seen time and the explicit criteria crossing."""
        if existing is not None:
            detection.first_seen_at = existing.first_seen_at
            detection.notes = detection.notes + [f"etat precedent : {existing.status.value}"]

    def commit(self, result: SeriesResult) -> list[LifecycleEvent]:
        """Store the detections and return the state transitions to publish."""
        events: list[LifecycleEvent] = []
        seen: set[str] = set()
        for detection in result.detections:
            seen.add(detection.id)
            self._stale_runs[detection.id] = 0
            previous_status = self._previous_state.get(detection.id)
            is_new = detection.id not in self.registry
            self.registry[detection.id] = detection

            if is_new:
                events.append(LifecycleEvent("SMC_DETECTED", detection))
                self._previous_state[detection.id] = detection.status
                continue

            if previous_status is not detection.status:
                mapping = {
                    DetectionStatus.CONFIRMED: "SMC_CONFIRMED",
                    DetectionStatus.INVALIDATED: "SMC_INVALIDATED",
                    DetectionStatus.MITIGATED: "SMC_MITIGATED",
                    DetectionStatus.FILLED: "SMC_FILLED",
                    DetectionStatus.EXPIRED: "SMC_EXPIRED",
                }
                event_type = mapping.get(detection.status)
                if event_type:
                    events.append(LifecycleEvent(event_type, detection, previous_status))
            self._previous_state[detection.id] = detection.status

        self._prune(result, seen)
        return events

    def _prune(self, result: SeriesResult, seen: set[str]) -> None:
        for key, detection in list(self.registry.items()):
            same_series = (
                detection.symbol == result.symbol and detection.timeframe.value == result.timeframe
            )
            if not same_series or key in seen:
                continue
            self._stale_runs[key] = self._stale_runs.get(key, 0) + 1
            if self._stale_runs[key] >= STALE_RUNS_BEFORE_DROP:
                self.registry.pop(key, None)
                self._stale_runs.pop(key, None)
                self._previous_state.pop(key, None)

        cap = self.params.global_.max_tracked
        if len(self.registry) > cap:
            ordered = sorted(
                self.registry.values(),
                key=lambda d: (d.detected_at_bar_time or 0, d.last_updated_at or datetime.min.replace(tzinfo=timezone.utc)),
            )
            for detection in ordered[: len(self.registry) - cap]:
                self.registry.pop(detection.id, None)
                self._stale_runs.pop(detection.id, None)
                self._previous_state.pop(detection.id, None)
            logger.warning("SMC/ICT registry pruned to %s entries", len(self.registry))

    # ---------------------------------------------------------------- reading
    def all(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        items = list(self.registry.values())
        if symbol:
            items = [d for d in items if d.symbol == normalize_symbol(symbol)]
        if timeframe:
            items = [d for d in items if d.timeframe.value == timeframe.upper()]
        return sorted(items, key=lambda d: (d.detected_at_bar_time or 0, d.pattern), reverse=True)

    def active(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return [
            d
            for d in self.all(symbol, timeframe)
            if d.status in (DetectionStatus.DETECTED, DetectionStatus.ACTIVE)
        ]

    def structure(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        structural = {"BOS", "CHOCH", "MSS"}
        return [d for d in self.all(symbol, timeframe) if d.pattern in structural]

    @property
    def parameters_version(self) -> str:
        payload = ",".join(
            f"{group}:{sorted(values.items())}" if isinstance(values, dict) else f"{group}:{values}"
            for group, values in sorted(self.params.snapshot().items())
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def stats(self) -> dict[str, object]:
        by_status: dict[str, int] = {}
        by_pattern: dict[str, int] = {}
        by_family: dict[str, int] = {}
        for detection in self.registry.values():
            by_status[detection.status.value] = by_status.get(detection.status.value, 0) + 1
            by_pattern[detection.pattern] = by_pattern.get(detection.pattern, 0) + 1
            family = str(detection.parameters.get("family", "?"))
            by_family[family] = by_family.get(family, 0) + 1
        return {
            "engine": ENGINE_NAME,
            "tracked": len(self.registry),
            "by_status": by_status,
            "by_pattern": by_pattern,
            "by_family": by_family,
            "parameters_version": self.parameters_version,
        }

    def clear(self) -> None:
        """Test helper."""
        self.registry.clear()
        self._stale_runs.clear()
        self._previous_state.clear()


def series_timeframe(value: str):
    """Timeframe enum from its value (kept tiny so the engine has no cycles)."""
    from app.schemas.market import Timeframe

    return Timeframe(value)


def _pip_and_digits(symbol: str) -> tuple[float, int]:
    """Pip size and digits, from the instrument catalog Phase 1/2 already uses.

    An unknown symbol falls back to the configured pip fallback (never to an
    invented precision): the note is explicit in the payload through
    ``pip_fallback``.
    """
    info = get_symbol_info(symbol)
    if info is not None:
        return float(info.pip_size), int(info.digits)
    fallback = SmcIctParams().global_.pip_fallback
    return float(fallback), 5 if fallback < 0.005 else 3


def _trigger_level(candidate: SmcCandidate) -> float | None:
    """The level whose break is watched for this object."""
    for name in ("BROKEN_SWING", "LEVEL", "ZONE_HIGH", "UPPER_PRICE", "POOL_LEVEL", "LIQUIDITY_LEVEL", "RANGE_HIGH"):
        if name in candidate.levels:
            return float(candidate.levels[name])
    return None


def _invalidation_level(candidate: SmcCandidate) -> float | None:
    if "ZONE_LOW" in candidate.levels:
        return float(candidate.levels["ZONE_LOW"])
    if "LOWER_PRICE" in candidate.levels:
        return float(candidate.levels["LOWER_PRICE"])
    if "RANGE_LOW" in candidate.levels:
        return float(candidate.levels["RANGE_LOW"])
    return None


def _confirmation_state(candidate: SmcCandidate) -> dict[str, object]:
    """How the object was established, in the words of its own pattern."""
    if candidate.pattern in ("BOS", "CHOCH", "MSS"):
        mode = str(candidate.measurements.get("break_mode", "CLOSE"))
        return {
            "confirmed": True,
            "level": candidate.levels.get("BROKEN_SWING"),
            "level_type": "SWING",
            "time": candidate.time,
            "price": candidate.levels.get("BREAK_CLOSE"),
            "note": f"cassure confirmee par une cloture (mode {mode})",
        }
    if candidate.pattern == "LIQUIDITY_SWEEP":
        return {
            "confirmed": True,
            "level": candidate.levels.get("LIQUIDITY_LEVEL"),
            "level_type": "LIQUIDITY",
            "time": candidate.extra.get("reentry_timestamp"),
            "price": candidate.levels.get("REENTRY"),
            "note": "reintegration confirmee par la cloture de la bougie de balayage",
        }
    if candidate.pattern in ("BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK"):
        trigger = candidate.extra.get("trigger_event") or {}
        return {
            "confirmed": True,
            "level": candidate.levels.get("ZONE_LOW") if candidate.direction == "BULLISH" else candidate.levels.get("ZONE_HIGH"),
            "level_type": "ORDER_BLOCK",
            "time": candidate.time,
            "price": candidate.levels.get("ORIGIN_CLOSE"),
            "note": f"declenche par {trigger.get('pattern')} en bougie {trigger.get('index')}",
        }
    if candidate.pattern == "BREAKER_BLOCK":
        return {
            "confirmed": True,
            "level": candidate.levels.get("ZONE_LOW") if candidate.direction == "BULLISH" else candidate.levels.get("ZONE_HIGH"),
            "level_type": "BREAKER",
            "time": candidate.time,
            "price": candidate.levels.get("ZONE_HIGH"),
            "note": "cycle ORDER_BLOCK -> INVALIDATION -> STRUCTURAL_BREAK -> BREAKER",
        }
    if candidate.pattern in ("BULLISH_FVG", "BEARISH_FVG"):
        return {
            "confirmed": True,
            "level": candidate.levels.get("LOWER_PRICE") if candidate.direction == "BULLISH" else candidate.levels.get("UPPER_PRICE"),
            "level_type": "FVG",
            "time": candidate.time,
            "price": candidate.levels.get("UPPER_PRICE") if candidate.direction == "BULLISH" else candidate.levels.get("LOWER_PRICE"),
            "note": "gap de trois bougies : bande jamais tradee",
        }
    if candidate.pattern in ("EQUAL_HIGH", "EQUAL_LOW", "LIQUIDITY_POOL_ESTIMATE"):
        return {
            "confirmed": True,
            "level": candidate.levels.get("LEVEL") or candidate.levels.get("POOL_LEVEL"),
            "level_type": "LIQUIDITY_LEVEL",
            "time": candidate.time,
            "price": candidate.levels.get("LEVEL") or candidate.levels.get("POOL_LEVEL"),
            "note": "niveau de liquidite estime, jamais un carnet d'ordres observe",
        }
    return {
        "confirmed": True,
        "level": None,
        "level_type": None,
        "time": candidate.time,
        "price": None,
        "note": "objet de contexte SMC/ICT",
    }


def _json_safe(value):
    from app.smc_ict.models import as_json

    return as_json(value)
