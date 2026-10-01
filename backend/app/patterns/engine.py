"""Chart pattern engine (Phase 2).

Pipeline for one series:

    OHLC (closed candles)
        -> pivots + ATR
        -> detectors (double top/bottom, H&S, triangles, wedges, rectangle,
           flags/pennants, support/resistance, channel)
        -> candidate -> PatternDetection (evidence, coordinates, drawing,
           confidence from explicit criteria)
        -> lifecycle (DETECTED -> CONFIRMED / INVALIDATED / EXPIRED)
        -> deduplication (one stable id per formation)

Breakout and retest are detected as separate events, never merged into the
pattern status. No synthetic price, no language model: everything comes from the
OHLC and the parameters in :mod:`app.patterns.params`.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.instruments import get_symbol_info, normalize_symbol
from app.logging_conf import get_logger
from app.patterns import drawing as drawing_builder
from app.patterns.confidence import score
from app.patterns.detectors import consolidations, flags, reversals, triangles
from app.patterns.geometry import fit_line
from app.patterns.models import BarContext, Candidate, Pivot
from app.patterns.params import PatternParams, params as default_params
from app.patterns.pivots import build_context, pips
from app.schemas.events import (
    BreakoutInfo,
    ConfirmationInfo,
    DetectionCategory,
    DetectionDirection,
    DetectionSource,
    DetectionStatus,
    InvalidationInfo,
    PatternDetection,
    RetestInfo,
    WatchedLevel,
)
from app.schemas.market import CandleSeries, Timeframe

logger = get_logger(__name__)

#: hard cap on simultaneous detections of the same pattern (anti-flood)
MAX_PER_PATTERN = 2
#: registry cap; oldest non-active entries are dropped first
MAX_TRACKED_DETECTIONS = 600
#: a detection missing from this many consecutive runs of its series is dropped
STALE_RUNS_BEFORE_DROP = 3

DETECTOR_NAMES = (
    "DOUBLE_TOP",
    "DOUBLE_BOTTOM",
    "HEAD_SHOULDERS",
    "INVERSE_HEAD_SHOULDERS",
    "ASCENDING_TRIANGLE",
    "DESCENDING_TRIANGLE",
    "SYMMETRICAL_TRIANGLE",
    "RISING_WEDGE",
    "FALLING_WEDGE",
    "RECTANGLE",
    "BULL_FLAG",
    "BEAR_FLAG",
    "BULL_PENNANT",
    "BEAR_PENNANT",
    "SUPPORT",
    "RESISTANCE",
    "CHANNEL",
)

#: breakout is reported as its own event, retest as another one
EVENT_BY_STATUS = {
    DetectionStatus.DETECTED: "PATTERN_DETECTED",
    DetectionStatus.CONFIRMED: "PATTERN_CONFIRMED",
    DetectionStatus.INVALIDATED: "PATTERN_INVALIDATED",
    DetectionStatus.EXPIRED: "PATTERN_EXPIRED",
}


@dataclass
class SeriesResult:
    """Outcome of one engine run on one series (reported by the scanner)."""

    symbol: str
    timeframe: str
    bars_analyzed: int
    pivots: int
    candidates: int
    detections: list[PatternDetection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class LifecycleEvent:
    """State transition to publish + persist."""

    event_type: str
    detection: PatternDetection
    previous_status: DetectionStatus | None = None
    breakout: BreakoutInfo | None = None
    retest: RetestInfo | None = None


def dedup_key(symbol: str, timeframe: str, pattern: str, candidate: Candidate) -> str:
    """Stable identity of a formation: pair + timeframe + pattern + its pivots.

    The pivots' real bar times are the discriminator, so the same geometry keeps
    the same key across events (and across restarts), while a genuinely new
    formation gets a new one.
    """
    payload = f"{symbol}|{timeframe}|{pattern}|{candidate.pivot_signature()}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"ct_{digest}"


class ChartPatternEngine:
    """Detects chartist formations on real OHLC series."""

    def __init__(self, params: PatternParams | None = None) -> None:
        self.params = params or default_params
        #: dedup_key -> PatternDetection (the live registry of the process)
        self.registry: dict[str, PatternDetection] = {}
        #: dedup_key -> number of consecutive runs of its series without a match
        self._stale_runs: dict[str, int] = {}
        #: dedup_key -> (status before this run, a retest had already been reported)
        self._previous_state: dict[str, tuple[DetectionStatus | None, bool]] = {}

    # ------------------------------------------------------------------ run
    def analyse(self, series: CandleSeries) -> SeriesResult:
        symbol = normalize_symbol(series.symbol)
        timeframe = series.timeframe.value
        started = time.perf_counter()
        info = get_symbol_info(symbol)
        digits = info.digits if info else 5
        pip_size = info.pip_size if info else self.params.globals.pip_fallback

        result = SeriesResult(symbol=symbol, timeframe=timeframe, bars_analyzed=0, pivots=0, candidates=0)

        if not self.params.enabled:
            result.notes.append("engine disabled by configuration")
            return result

        globals_ = self.params.globals
        context = build_context(
            symbol,
            timeframe,
            series.candles,
            digits=digits,
            pip_size=pip_size,
            left=globals_.pivot_left,
            right=globals_.pivot_right,
            atr_period=globals_.atr_period,
            max_pivots=globals_.max_pivots,
            atr_slow_period=globals_.atr_slow_period,
        )
        result.bars_analyzed = len(context.candles)
        result.pivots = len(context.pivots)

        if len(context.candles) < globals_.min_bars_required:
            result.notes.append(
                f"not enough closed bars ({len(context.candles)} < {globals_.min_bars_required})"
            )
            return result
        if not context.pivots:
            result.notes.append("no confirmed pivot in the window")
            return result

        candidates: list[Candidate] = []
        for detector in (
            reversals.detect_double_top,
            reversals.detect_double_bottom,
            reversals.detect_head_shoulders,
            reversals.detect_inverse_head_shoulders,
            triangles.detect_triangles,
            triangles.detect_wedges,
            consolidations.detect_rectangle,
            flags.detect_flags,
            consolidations.detect_support_resistance,
            triangles.detect_channels,
        ):
            try:
                candidates.extend(detector(context, self.params))
            except Exception as exc:  # a broken detector must not stop the others
                logger.exception("Detector %s failed on %s %s: %s", detector.__name__, symbol, timeframe, exc)
                result.notes.append(f"detector {detector.__name__} error: {type(exc).__name__}")

        result.candidates = len(candidates)

        # anti-flood: keep at most MAX_PER_PATTERN detections of the same pattern
        limit_per_pattern = MAX_PER_PATTERN

        kept: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            bucket = kept.setdefault(candidate.pattern, [])
            if len(bucket) < limit_per_pattern:
                bucket.append(candidate)

        fresh_ids: set[str] = set()
        for pattern, bucket in kept.items():
            for candidate in bucket:
                detection = self._to_detection(candidate, context)
                existing = self.registry.get(detection.id)
                self._previous_state[detection.id] = (
                    existing.status if existing else None,
                    existing.retest is not None if existing else False,
                )
                self._apply_lifecycle(detection, context, existing)
                fresh_ids.add(detection.id)
                result.detections.append(detection)

        # A formation found three bars ago must keep being watched even when the
        # detector no longer re-derives it (its pivots aged out of the window):
        # the breakout / invalidation / expiry decision depends on the new bars.
        result.detections.extend(self._refresh_tracked(symbol, timeframe, context, fresh_ids))

        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    def _refresh_tracked(
        self, symbol: str, timeframe: str, context: BarContext, fresh_ids: set[str]
    ) -> list[PatternDetection]:
        """Re-evaluate the live formations of this series on the newest bars."""
        refreshed: list[PatternDetection] = []
        for detection in list(self.registry.values()):
            if detection.symbol != symbol or detection.timeframe.value != timeframe:
                continue
            if detection.id in fresh_ids:
                continue
            if detection.status is DetectionStatus.EXPIRED:
                continue
            before = (detection.status, detection.breakout, detection.retest)
            self._previous_state[detection.id] = (detection.status, detection.retest is not None)
            self._apply_lifecycle(detection, context, detection)
            if (detection.status, detection.breakout, detection.retest) != before:
                logger.debug(
                    "Tracked %s %s %s -> %s", symbol, timeframe, detection.pattern, detection.status.value
                )
            refreshed.append(detection)
        return refreshed

    # -------------------------------------------------------------- mapping
    @staticmethod
    def _json_safe(value):
        """Turn Pivot objects into plain dicts so every payload is serialisable."""
        if isinstance(value, Pivot):
            return value.as_dict()
        if isinstance(value, dict):
            return {key: ChartPatternEngine._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [ChartPatternEngine._json_safe(item) for item in value]
        return value

    def _to_detection(self, candidate: Candidate, context: BarContext) -> PatternDetection:
        spec, coordinates = drawing_builder.build(candidate, context)
        confidence, factor_details = score(candidate.factors)
        key = dedup_key(context.symbol, context.timeframe, candidate.pattern, candidate)

        direction = {
            "BULLISH": DetectionDirection.BULLISH,
            "BEARISH": DetectionDirection.BEARISH,
            "NEUTRAL": DetectionDirection.NEUTRAL,
        }[candidate.direction]

        return PatternDetection(
            id=key,
            dedup_key=key,
            symbol=context.symbol,
            timeframe=Timeframe(context.timeframe),
            category=DetectionCategory.CHARTISTE,
            pattern=candidate.pattern,
            direction=direction,
            confidence=confidence,
            confidence_factors=factor_details,
            evidence=list(candidate.evidence),
            evidence_points=self._json_safe(candidate.evidence_points),
            coordinates=coordinates,
            drawing=spec,
            parameters=candidate.parameters,
            confirmation=ConfirmationInfo(
                confirmed=False,
                level=candidate.breakout_levels[0][1] if candidate.breakout_levels else None,
                level_type=candidate.breakout_levels[0][0] if candidate.breakout_levels else None,
                note="en attente du breakout de confirmation",
            ),
            invalidation=InvalidationInfo(
                invalidated=False,
                level=candidate.invalidation_level,
                level_type=candidate.invalidation_level_type,
                reason=candidate.invalidation_reason,
            ),
            status=DetectionStatus.DETECTED,
            watch_levels=[
                WatchedLevel(
                    level_type=level_type,
                    price=round(price, 10),
                    direction=DetectionDirection(direction),
                    role="CONFIRMATION",
                )
                for level_type, price, direction in candidate.breakout_levels
            ],
            source_engine=DetectionSource.CHART_PATTERN_ENGINE,
            detected_at_bar_time=candidate.detected_at_bar_time,
            first_seen_at=datetime.now(tz=timezone.utc),
            last_updated_at=datetime.now(tz=timezone.utc),
            bars_in_window=context.last_index + 1,
            notes=candidate.notes,
        )

    # ----------------------------------------------------------- lifecycle
    def _apply_lifecycle(
        self, detection: PatternDetection, context: BarContext, existing: PatternDetection | None
    ) -> None:
        """Move DETECTED -> CONFIRMED / INVALIDATED and attach breakout/retest."""
        if existing is not None:
            # keep the original creation time and the earliest confirmation
            detection.first_seen_at = existing.first_seen_at
            detection.status = existing.status
            detection.confirmation = existing.confirmation
            detection.invalidation = existing.invalidation
            detection.breakout = existing.breakout
            detection.retest = existing.retest

        window_start = detection.detected_at_bar_time or 0
        bars = _bars_from(context, window_start)

        if detection.status is DetectionStatus.DETECTED:
            breakout = self._detect_breakout(detection, context, bars)
            if breakout is not None:
                detection.breakout = breakout
                detection.status = DetectionStatus.CONFIRMED
                detection.confirmation = ConfirmationInfo(
                    confirmed=True,
                    level=breakout.level,
                    level_type=breakout.level_type,
                    breakout_time=breakout.breakout_time,
                    breakout_price=breakout.breakout_price,
                    breakout_candle_time=breakout.confirming_candle_time,
                    candles_to_confirm=breakout.candles_to_breakout,
                    volume=breakout.volume,
                    note=f"cloture {breakout.direction.value.lower()} au-dela de {breakout.level_type}",
                )
                # a confirmed breakout upgrades the score (real validation)
                extra = ("Breakout confirme", True, self.params.weights.breakout,
                         f"cassure de {breakout.level_type} a {breakout.breakout_price}")
                factors = [(f.criterion, f.passed, f.weight, f.detail) for f in detection.confidence_factors]
                factors.append(extra)
                detection.confidence, detection.confidence_factors = score(factors)
                detection.evidence = detection.evidence + [
                    f"BREAKOUT : cloture a {breakout.breakout_price} au-dela de "
                    f"{breakout.level_type} {breakout.level} ({breakout.candles_to_breakout} bougies apres la formation)"
                ]
            else:
                self._check_invalidation(detection, context, bars)

        if detection.status is DetectionStatus.CONFIRMED and detection.breakout is not None:
            retest = self._detect_retest(detection, context, bars)
            if retest is not None:
                detection.retest = retest
                detection.breakout = detection.breakout.model_copy(update={"retested": True})
                detection.evidence = detection.evidence + [
                    f"RETEST : retour au niveau {retest.breakout_level} a "
                    f"{retest.retest_price} ({retest.distance_to_level_pips} pips), "
                    f"{'confirme' if retest.confirmed else 'sans confirmation'}"
                ]

        # expiry: nothing happened in the allowed window
        if detection.status is DetectionStatus.DETECTED:
            limit = _max_bars(detection, self.params)
            if limit is not None and bars and (context.last_index - bars[0][0]) > limit:
                detection.status = DetectionStatus.EXPIRED
                detection.notes = detection.notes + [
                    f"expiree : aucun breakout en {limit} bougies (fenetre de confirmation depassee)"
                ]

        detection.last_updated_at = datetime.now(tz=timezone.utc)

    def _detect_breakout(
        self, detection: PatternDetection, context: BarContext, bars: list[tuple[int, object]]
    ) -> BreakoutInfo | None:
        """A breakout needs a real close beyond the level plus a buffer."""
        levels = _breakout_levels(detection)
        if not levels:
            return None
        cfg = self.params.breakout
        first_index = bars[0][0] if bars else context.last_index

        best: BreakoutInfo | None = None
        for level_type, level, direction in levels:
            buffer_ = cfg.buffer_pips * context.pip_size
            for index, candle in bars:
                if direction == "BULLISH" and candle.close > level + buffer_:
                    best = _breakout_info(
                        detection, level_type, level, "BULLISH", candle, index, context, cfg, first_index
                    )
                    break
                if direction == "BEARISH" and candle.close < level - buffer_:
                    best = _breakout_info(
                        detection, level_type, level, "BEARISH", candle, index, context, cfg, first_index
                    )
                    break
            if best is not None:
                break
        return best

    def _detect_retest(
        self, detection: PatternDetection, context: BarContext, bars: list[tuple[int, object]]
    ) -> RetestInfo | None:
        """Retest = return to a broken level, only after a confirmed breakout."""
        breakout = detection.breakout
        if breakout is None or breakout.retested:
            return None
        cfg = self.params.breakout
        tolerance = max(cfg.retest_tolerance_pips, 1.0) * context.pip_size
        after = [(index, candle) for index, candle in bars if candle.time > breakout.confirming_candle_time]
        if not after:
            return None

        for index, candle in after[1:]:  # a retest needs at least one bar in between
            if index - _index_of(context, breakout.confirming_candle_time) > cfg.retest_max_bars:
                break
            distance = abs(candle.low - breakout.level) if breakout.direction == DetectionDirection.BULLISH else abs(candle.high - breakout.level)
            if distance > tolerance:
                continue
            distance_pips = pips(distance, context.pip_size)
            if distance_pips < cfg.retest_min_distance_pips:
                continue
            # confirmation: the candle closes back on the breakout side
            confirmed = (
                candle.close > breakout.level
                if breakout.direction is DetectionDirection.BULLISH
                else candle.close < breakout.level
            )
            return RetestInfo(
                breakout_level=breakout.level,
                breakout_candle_time=breakout.confirming_candle_time,
                retest_candle_time=candle.time,
                retest_price=candle.low if breakout.direction is DetectionDirection.BULLISH else candle.high,
                distance_to_level_pips=round(distance_pips, 2),
                confirmed=confirmed,
                confirmation_candle_time=candle.time if confirmed else None,
                candles_after_breakout=index - _index_of(context, breakout.confirming_candle_time),
            )
        return None

    def _check_invalidation(
        self, detection: PatternDetection, context: BarContext, bars: list[tuple[int, object]]
    ) -> None:
        level = detection.invalidation.level
        if level is None or not bars:
            return
        direction = detection.direction
        for index, candle in bars:
            if direction is DetectionDirection.BEARISH and candle.close > level:
                detection.status = DetectionStatus.INVALIDATED
                detection.invalidation = detection.invalidation.model_copy(
                    update={
                        "invalidated": True,
                        "invalidated_at": candle.time,
                        "reason": f"cloture {candle.close} au-dessus du niveau d'invalidation {level} "
                        f"({detection.invalidation.reason or 'niveau depasse'})",
                    }
                )
                detection.evidence = detection.evidence + [
                    f"INVALIDATION : cloture {candle.close} au-dela de {level} a la barre {index}"
                ]
                return
            if direction is DetectionDirection.BULLISH and candle.close < level:
                detection.status = DetectionStatus.INVALIDATED
                detection.invalidation = detection.invalidation.model_copy(
                    update={
                        "invalidated": True,
                        "invalidated_at": candle.time,
                        "reason": f"cloture {candle.close} sous le niveau d'invalidation {level} "
                        f"({detection.invalidation.reason or 'niveau depasse'})",
                    }
                )
                detection.evidence = detection.evidence + [
                    f"INVALIDATION : cloture {candle.close} au-dela de {level} a la barre {index}"
                ]
                return

    # ------------------------------------------------------------ registry
    def commit(self, result: SeriesResult) -> list[LifecycleEvent]:
        """Store the detections and return the state transitions to publish."""
        events: list[LifecycleEvent] = []
        seen: set[str] = set()
        for detection in result.detections:
            seen.add(detection.id)
            self._stale_runs[detection.id] = 0
            previous_status, had_retest = self._previous_state.get(detection.id, (None, False))
            previous_is_entry = self.registry.get(detection.id) is not None
            self.registry[detection.id] = detection
            if not previous_is_entry:
                events.append(LifecycleEvent("PATTERN_DETECTED", detection))
                if detection.status is DetectionStatus.CONFIRMED:
                    # both happened inside the same run: announce both, in order
                    events.append(
                        LifecycleEvent(
                            "BREAKOUT_DETECTED",
                            detection,
                            previous_status=DetectionStatus.DETECTED,
                            breakout=detection.breakout,
                        )
                    )
                    events.append(LifecycleEvent("PATTERN_CONFIRMED", detection, DetectionStatus.DETECTED))
                if detection.retest is not None:
                    events.append(LifecycleEvent("RETEST_DETECTED", detection, retest=detection.retest))
                continue

            if previous_status is not detection.status:
                if detection.status is DetectionStatus.CONFIRMED:
                    events.append(
                        LifecycleEvent(
                            "BREAKOUT_DETECTED", detection, previous_status, breakout=detection.breakout
                        )
                    )
                    events.append(LifecycleEvent("PATTERN_CONFIRMED", detection, previous_status))
                elif detection.status is DetectionStatus.INVALIDATED:
                    events.append(LifecycleEvent("PATTERN_INVALIDATED", detection, previous_status))
                elif detection.status is DetectionStatus.EXPIRED:
                    events.append(LifecycleEvent("PATTERN_EXPIRED", detection, previous_status))

            if detection.retest is not None and not had_retest:
                events.append(LifecycleEvent("RETEST_DETECTED", detection, previous_status, retest=detection.retest))

        self._prune(result, seen)
        self._previous_state.clear()
        return events

    def _prune(self, result: SeriesResult, seen: set[str]) -> None:
        """Drop entries that left the analysed window, then apply the hard cap."""
        for key, detection in list(self.registry.items()):
            same_series = detection.symbol == result.symbol and detection.timeframe.value == result.timeframe
            if not same_series or key in seen:
                continue
            self._stale_runs[key] = self._stale_runs.get(key, 0) + 1
            if self._stale_runs[key] >= STALE_RUNS_BEFORE_DROP:
                self.registry.pop(key, None)
                self._stale_runs.pop(key, None)

        if len(self.registry) > MAX_TRACKED_DETECTIONS:
            ordered = sorted(
                self.registry.values(),
                key=lambda d: (d.status is DetectionStatus.DETECTED, d.last_updated_at or datetime.min.replace(tzinfo=timezone.utc)),
            )
            for detection in ordered[: len(self.registry) - MAX_TRACKED_DETECTIONS]:
                self.registry.pop(detection.id, None)
                self._stale_runs.pop(detection.id, None)
            logger.warning("Detection registry pruned to %s entries", len(self.registry))

    def active(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        items = [
            detection
            for detection in self.registry.values()
            if detection.status is DetectionStatus.DETECTED
        ]
        if symbol:
            items = [d for d in items if d.symbol == normalize_symbol(symbol)]
        if timeframe:
            items = [d for d in items if d.timeframe.value == timeframe.upper()]
        return sorted(items, key=lambda d: (d.detected_at_bar_time or 0, d.symbol), reverse=True)

    def all(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        items = list(self.registry.values())
        if symbol:
            items = [d for d in items if d.symbol == normalize_symbol(symbol)]
        if timeframe:
            items = [d for d in items if d.timeframe.value == timeframe.upper()]
        return sorted(items, key=lambda d: (d.detected_at_bar_time or 0, d.symbol), reverse=True)

    def stats(self) -> dict[str, object]:
        by_status: dict[str, int] = {}
        by_pattern: dict[str, int] = {}
        for detection in self.registry.values():
            by_status[detection.status.value] = by_status.get(detection.status.value, 0) + 1
            by_pattern[detection.pattern] = by_pattern.get(detection.pattern, 0) + 1
        return {
            "tracked": len(self.registry),
            "by_status": by_status,
            "by_pattern": by_pattern,
        }

    def clear(self) -> None:
        """Test helper."""
        self.registry.clear()
        self._stale_runs.clear()


# ----------------------------------------------------------------- helpers
def _max_bars(detection: PatternDetection, params: PatternParams) -> int | None:
    family = detection.pattern
    if family in ("DOUBLE_TOP", "DOUBLE_BOTTOM"):
        return params.double_top_bottom.max_bars_to_confirm
    if family in ("HEAD_SHOULDERS", "INVERSE_HEAD_SHOULDERS"):
        return params.head_shoulders.max_bars_to_confirm
    if "TRIANGLE" in family:
        return params.triangle.max_bars_to_confirm
    if "WEDGE" in family:
        return params.wedge.max_bars_to_confirm
    if family == "RECTANGLE":
        return params.rectangle.max_bars_to_confirm
    if "FLAG" in family or "PENNANT" in family:
        return params.flags.max_bars_to_confirm
    return None


def _bars_from(context: BarContext, start_time: int) -> list[tuple[int, object]]:
    """Bars at or after the formation completion (breakout search window)."""
    for index, candle in enumerate(context.candles):
        if candle.time >= start_time:
            return list(enumerate(context.candles[index:], start=index))
    return []


def _index_of(context: BarContext, time: int) -> int:
    index = context.index_of_time(time)
    return context.last_index if index is None else index


def _breakout_levels(detection: PatternDetection) -> list[tuple[str, float, str]]:
    """Confirmation levels, read from the detection payload (no hidden state).

    Only levels whose break goes *in the direction of the pattern* can confirm it:
    a close above both peaks of a double top is its invalidation, never its
    confirmation. NEUTRAL patterns (triangles, rectangles, channels) keep both
    sides, each with its own direction.
    """
    return [
        (level.level_type, level.price, level.direction.value)
        for level in detection.watch_levels
        if level.role == "CONFIRMATION"
        and (
            detection.direction is DetectionDirection.NEUTRAL
            or level.direction is detection.direction
        )
    ]


def _breakout_info(
    detection: PatternDetection,
    level_type: str,
    level: float,
    direction: str,
    candle,
    index: int,
    context: BarContext,
    cfg,
    first_index: int,
) -> BreakoutInfo:
    return BreakoutInfo(
        parent_detection_id=detection.id,
        level=round(level, 10),
        level_type=level_type,
        direction=DetectionDirection(direction),
        breakout_price=candle.close,
        breakout_time=candle.time,
        confirming_candle_time=candle.time,
        candles_to_breakout=max(0, index - first_index),
        buffer_pips=cfg.buffer_pips,
        # Never invent volume: a spot FX feed that reports 0 has simply no volume,
        # and "0" would be a lie - so it is stored as "not available".
        volume=candle.volume if candle.volume not in (None, 0) else None,
    )
