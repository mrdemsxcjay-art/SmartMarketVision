"""Price-action engine (Phase 3).

Pipeline for one series:

    closed OHLC
        -> candle measurements (body, wicks, ratios) + volatility scale
        -> candlestick detectors (engulfing, pin bar, hammer / shooting star,
           inside bar, outside bar, doji)
        -> structural detectors (impulsion, consolidation, rejection,
           failed breakout)
        -> level context from the *chartist* engine (support, resistance,
           rectangle edges, channels, breakout levels) - never recomputed here
        -> PatternDetection (evidence, measurements, coordinates, drawing,
           confidence = weighted share of the criteria that passed)
        -> lifecycle DETECTED -> CONFIRMED / INVALIDATED / EXPIRED
        -> deduplication (one stable id per pattern and per real candle)

Rules:

* closed candles only - the forming bar is never used;
* ``category=PRICE_ACTION``, ``source_engine=PRICE_ACTION_ENGINE``;
* no trading signal, no order, no position sizing: the engine observes and
  explains, the human decides;
* structure events (IMPULSION, CONSOLIDATION) are *states*: one active state per
  pair/timeframe/pattern, refreshed in place, never multiplied per bar;
* a FAILED_BREAKOUT consumes the breakout already confirmed by Phase 2, so the
  project keeps exactly one breakout mechanism.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.instruments import get_symbol_info, normalize_symbol
from app.logging_conf import get_logger
from app.patterns import drawing as drawing_builder
from app.patterns.confidence import score
from app.patterns.models import Candidate
from app.price_action.candles import CandleMetrics, measure_all, pips
from app.price_action.detectors import candlestick, structural
from app.price_action.models import BreakoutRef, ConfluenceGroup, LevelRef, ScanContext
from app.price_action.params import PriceActionParams, params as default_params
from app.schemas.events import (
    BreakoutInfo,
    ConfirmationInfo,
    DetectionCategory,
    DetectionDirection,
    DetectionSource,
    DetectionStatus,
    InvalidationInfo,
    PatternDetection,
    WatchedLevel,
)
from app.schemas.market import CandleSeries, Timeframe

logger = get_logger(__name__)

ENGINE_NAME = "PRICE_ACTION_ENGINE"

#: a detection missing from this many consecutive runs of its series is dropped
STALE_RUNS_BEFORE_DROP = 3

#: patterns describing a *current state* of the market (refreshed, never multiplied)
STATE_PATTERNS = frozenset({"IMPULSION", "CONSOLIDATION"})

EVENT_BY_STATUS = {
    DetectionStatus.DETECTED: "PRICE_ACTION_DETECTED",
    DetectionStatus.CONFIRMED: "PRICE_ACTION_CONFIRMED",
    DetectionStatus.INVALIDATED: "PRICE_ACTION_INVALIDATED",
    DetectionStatus.EXPIRED: "PRICE_ACTION_EXPIRED",
}

CANDLE_DETECTORS = (
    candlestick.detect_bullish_engulfing,
    candlestick.detect_bearish_engulfing,
    candlestick.detect_bullish_pin_bar,
    candlestick.detect_bearish_pin_bar,
    candlestick.detect_hammer,
    candlestick.detect_shooting_star,
    candlestick.detect_inside_bar,
    candlestick.detect_outside_bar,
    candlestick.detect_doji,
)


@dataclass
class SeriesResult:
    """Outcome of one price-action run on one series."""

    symbol: str
    timeframe: str
    bars_analyzed: int
    candidates: int
    detections: list[PatternDetection] = field(default_factory=list)
    structure: list[str] = field(default_factory=list)
    context: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class LifecycleEvent:
    """State transition to publish + persist."""

    event_type: str
    detection: PatternDetection
    previous_status: DetectionStatus | None = None
    breakout: BreakoutInfo | None = None
    extra: dict[str, object] = field(default_factory=dict)


def dedup_key(
    symbol: str,
    timeframe: str,
    pattern: str,
    candle_time: int,
    extra: list[int] | None = None,
    level_ref: str | None = None,
) -> str:
    """Stable identity: pair + timeframe + pattern + the real candle it is tied to.

    ``extra`` carries the other real bar times that identify a multi-bar event
    (breakout candle + failure candle of a FAILED_BREAKOUT, for instance) so two
    genuinely different events can never share an id, and the same event can
    never be emitted twice.

    ``level_ref`` carries the real level the event is tied to, for the detectors
    that are emitted **once per chartist level** (REJECTION, FAILED_BREAKOUT): one
    candle can reject or invalidate several distinct levels, and those are distinct
    detections. It comes from real values only (published level id + price), never
    from a threshold. Without it, two of them shared an id and the persistence layer
    refused the whole batch - measured on real candles before the fix.
    """
    payload = f"{symbol}|{timeframe}|{pattern}|{candle_time}"
    if extra:
        payload += "|" + ",".join(str(value) for value in sorted(extra))
    if level_ref:
        payload += "|level=" + level_ref
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"pa_{digest}"


def _atr(metrics: list[CandleMetrics], period: int) -> float:
    """Mean true range over the last ``period`` bars (simple, documented average)."""
    if not metrics:
        return 0.0
    window = metrics[-max(1, period) :]
    start = len(metrics) - len(window)
    ranges: list[float] = []
    for offset, metric in enumerate(window):
        index = start + offset
        if index == 0:
            ranges.append(metric.range)
        else:
            previous_close = metrics[index - 1].close
            ranges.append(
                max(metric.high - metric.low, abs(metric.high - previous_close), abs(metric.low - previous_close))
            )
    return statistics.fmean(ranges) if ranges else 0.0


class PriceActionEngine:
    """Detects price-action patterns and structure on real OHLC series."""

    def __init__(self, params: PriceActionParams | None = None) -> None:
        self.params = params or default_params
        #: dedup_key -> PatternDetection (live registry of the process)
        self.registry: dict[str, PatternDetection] = {}
        self._stale_runs: dict[str, int] = {}
        self._previous_state: dict[str, tuple[DetectionStatus | None, bool]] = {}
        #: (symbol, timeframe, pattern) -> id of the active state detection
        self._state_active: dict[tuple[str, str, str], str] = {}

    # -------------------------------------------------------------------- run
    def analyse(
        self,
        series: CandleSeries,
        chartist: list[PatternDetection] | None = None,
    ) -> SeriesResult:
        """Analyse one series on its closed candles.

        ``chartist`` is the current chartist state of the same pair/timeframe: it
        provides the real levels (support/resistance/rectangle/channel) and the
        confirmed breakouts. It is optional - without it the engine only reports
        candlestick geometry.
        """
        symbol = normalize_symbol(series.symbol)
        timeframe = series.timeframe.value
        started = time.perf_counter()
        info = get_symbol_info(symbol)
        digits = info.digits if info else 5
        pip_size = info.pip_size if info else self.params.globals.pip_fallback

        result = SeriesResult(symbol=symbol, timeframe=timeframe, bars_analyzed=0, candidates=0)
        if not self.params.enabled:
            result.notes.append("engine disabled by configuration")
            return result

        globals_ = self.params.globals
        candles = list(series.closed_candles or series.candles)[-globals_.window_bars :]
        metrics = measure_all(candles)
        result.bars_analyzed = len(metrics)
        if len(metrics) < globals_.min_bars_required:
            result.notes.append(f"not enough closed bars ({len(metrics)} < {globals_.min_bars_required})")
            return result

        atr = _atr(metrics, globals_.atr_period)
        atr_slow = _atr(metrics, globals_.atr_slow_period)
        context = ScanContext(
            symbol=symbol,
            timeframe=timeframe,
            metrics=metrics,
            params=self.params,
            atr=atr_slow if atr_slow > 0 else atr,
            pip_size=pip_size,
            digits=digits,
        )

        levels = _levels_from_chartist(chartist or [], metrics, pip_size, self.params, context.atr)
        breakouts = _breakouts_from_chartist(chartist or [], metrics)

        candidates: list[Candidate] = []
        for detector in CANDLE_DETECTORS:
            try:
                candidates.extend(detector(context))
            except Exception as exc:  # one broken detector must not stop the others
                logger.exception("Price-action detector %s failed on %s %s", detector.__name__, symbol, timeframe)
                result.notes.append(f"detector {detector.__name__} error: {type(exc).__name__}")

        for structural_detector in (
            structural.detect_impulsion,
            structural.detect_consolidation,
        ):
            try:
                candidates.extend(structural_detector(context))
            except Exception as exc:
                logger.exception("Structure detector %s failed on %s %s", structural_detector.__name__, symbol, timeframe)
                result.notes.append(f"detector {structural_detector.__name__} error: {type(exc).__name__}")

        if levels:
            try:
                candidates.extend(structural.detect_rejection(context, levels))
            except Exception as exc:
                logger.exception("Rejection detector failed on %s %s", symbol, timeframe)
                result.notes.append(f"detector detect_rejection error: {type(exc).__name__}")
        if breakouts:
            try:
                candidates.extend(structural.detect_failed_breakout(context, breakouts))
            except Exception as exc:
                logger.exception("Failed-breakout detector failed on %s %s", symbol, timeframe)
                result.notes.append(f"detector detect_failed_breakout error: {type(exc).__name__}")

        result.candidates = len(candidates)
        result.structure = [c.pattern for c in candidates if c.pattern in STATE_PATTERNS]
        result.context = {
            "levels_available": len(levels),
            "breakouts_available": len(breakouts),
            "chartist_detections": len(chartist or []),
            "atr": round(context.atr, 6),
            "parameters_version": self.parameters_version,
        }

        fresh_ids: set[str] = set()
        state_ids: dict[tuple[str, str, str], str] = {}
        for candidate in candidates:
            detection = self._to_detection(candidate, context, levels, chartist or [])
            existing = self.registry.get(detection.id)
            self._previous_state[detection.id] = (
                existing.status if existing else None,
                existing.retest is not None if existing else False,
            )
            self._apply_lifecycle(detection, context, existing)
            fresh_ids.add(detection.id)
            result.detections.append(detection)
            if detection.pattern in STATE_PATTERNS:
                state_ids[(symbol, timeframe, detection.pattern)] = detection.id

        result.detections.extend(self._refresh_tracked(symbol, timeframe, context, fresh_ids, state_ids))
        result.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    @property
    def parameters_version(self) -> str:
        """Short hash of the parameter set: same params + same bars = same result."""
        payload = json.dumps(self.params.snapshot(), sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]

    # ---------------------------------------------------------------- mapping
    def _to_detection(
        self,
        candidate: Candidate,
        context: ScanContext,
        levels: list[LevelRef],
        chartist: list[PatternDetection],
    ) -> PatternDetection:
        spec, coordinates = drawing_builder.build(candidate, context)
        confidence, factor_details = score(candidate.factors)

        anchor = candidate.detected_at_bar_time or (context.metrics[-1].time if context.metrics else 0)
        key = dedup_key(
            context.symbol,
            context.timeframe,
            candidate.pattern,
            anchor,
            candidate.extra_signature,
            candidate.level_identity,
        )

        direction = {
            "BULLISH": DetectionDirection.BULLISH,
            "BEARISH": DetectionDirection.BEARISH,
            "NEUTRAL": DetectionDirection.NEUTRAL,
        }[candidate.direction]

        level_context, context_criteria = self._level_context(candidate, context, levels, chartist)
        evidence_points = dict(_json_safe(candidate.evidence_points))
        evidence_points["level_context"] = level_context
        evidence_points["context_criteria"] = context_criteria
        evidence_points["lifecycle"] = {
            "anchor_candle_time": anchor,
            "watch_from_index": candidate.watch_from_index,
            "max_bars_to_confirm": candidate.max_bars_to_confirm,
            "state_pattern": candidate.pattern in STATE_PATTERNS,
        }
        evidence_points["parameters_version"] = self.parameters_version
        evidence_points["candle_measurements_available"] = [
            "body_size",
            "upper_wick",
            "lower_wick",
            "range",
            "body_ratio",
            "wick_ratios",
        ]

        notes = list(candidate.notes)
        if level_context["label"]:
            notes.append(f"CONTEXTE: {level_context['label']}")

        return PatternDetection(
            id=key,
            dedup_key=key,
            symbol=context.symbol,
            timeframe=Timeframe(context.timeframe),
            category=DetectionCategory.PRICE_ACTION,
            pattern=candidate.pattern,
            direction=direction,
            confidence=confidence,
            confidence_factors=factor_details,
            evidence=list(candidate.evidence),
            evidence_points=evidence_points,
            coordinates=coordinates,
            drawing=spec,
            parameters=candidate.parameters
            | {
                "engine": {
                    "scan_bars": self.params.globals.scan_bars,
                    "window_bars": self.params.globals.window_bars,
                    "atr_period": self.params.globals.atr_period,
                    "atr_slow_period": self.params.globals.atr_slow_period,
                    "confirmation_buffer_pips": self.params.globals.confirmation_buffer_pips,
                    "invalidation_buffer_pips": self.params.globals.invalidation_buffer_pips,
                },
                "parameters_version": self.parameters_version,
            },
            confirmation=ConfirmationInfo(
                confirmed=False,
                level=candidate.breakout_levels[0][1] if candidate.breakout_levels else None,
                level_type=candidate.breakout_levels[0][0] if candidate.breakout_levels else None,
                note=(
                    "en attente d'une cloture au-dela du declencheur"
                    if candidate.breakout_levels
                    else "evenement d'observation : aucune confirmation attendue"
                ),
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
                    direction=DetectionDirection(level_direction),
                    role="CONFIRMATION",
                )
                for level_type, price, level_direction in candidate.breakout_levels
            ]
            + (
                [
                    WatchedLevel(
                        level_type=candidate.invalidation_level_type or "INVALIDATION",
                        price=round(candidate.invalidation_level, 10),
                        direction=(
                            DetectionDirection.BEARISH
                            if direction is DetectionDirection.BULLISH
                            else DetectionDirection.BULLISH
                        ),
                        role="INVALIDATION",
                    )
                ]
                if candidate.invalidation_level is not None
                else []
            ),
            source_engine=DetectionSource.PRICE_ACTION_ENGINE,
            detected_at_bar_time=anchor,
            first_seen_at=datetime.now(tz=timezone.utc),
            last_updated_at=datetime.now(tz=timezone.utc),
            bars_in_window=context.metrics[-1].index + 1 if context.metrics else 0,
            notes=notes,
        )

    # -------------------------------------------------------- level context
    def _level_context(
        self,
        candidate: Candidate,
        context: ScanContext,
        levels: list[LevelRef],
        chartist: list[PatternDetection],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Relations between an isolated pattern and the real surrounding structure.

        The result is **informative**: it never modifies ``confidence`` and never
        produces a recommendation. It only says, with numbers, whether the pattern
        sits on a real level or inside an active chartist formation.
        """
        cfg = self.params.levels
        pip_size = context.pip_size
        anchor = candidate.detected_at_bar_time or (context.metrics[-1].time if context.metrics else 0)
        index = _index_of_time(context.metrics, anchor)

        zone_low, zone_high = _candidate_zone(candidate)
        proximity = context.min_size(cfg.proximity_pips, cfg.proximity_atr)

        relations: list[dict[str, object]] = []
        for level in levels:
            distance = _distance_to_zone(level.price, zone_low, zone_high)
            tolerance = max(proximity, level.tolerance)
            if distance > tolerance:
                continue
            relations.append(
                {
                    "kind": level.kind,
                    "price": level.price,
                    "source": level.source,
                    "source_id": level.source_id,
                    "distance_pips": round(pips(distance, pip_size), 2),
                    "tolerance_pips": round(pips(tolerance, pip_size), 2),
                    "age_bars": level.age_bars,
                    "same_side": _same_side(level.price, zone_low, zone_high, candidate.direction),
                }
            )
        relations.sort(key=lambda item: item["distance_pips"])
        nearest = relations[0] if relations else None

        label = None
        if nearest is not None and cfg.context_labels:
            label = f"{candidate.pattern}_AT_{nearest['kind']}"

        window = self.params.confluence.window_bars
        overlapping: list[dict[str, object]] = []
        for detection in chartist:
            if detection.status not in (DetectionStatus.DETECTED, DetectionStatus.CONFIRMED):
                continue
            bar_time = detection.detected_at_bar_time
            if bar_time is None or index is None:
                continue
            other_index = _index_of_time(context.metrics, bar_time)
            if other_index is None:
                continue
            distance_bars = abs(index - other_index)
            if distance_bars > window:
                continue
            overlapping.append(
                {
                    "id": detection.id,
                    "pattern": detection.pattern,
                    "status": detection.status.value,
                    "direction": detection.direction.value,
                    "detected_at_bar_time": bar_time,
                    "bars_away": distance_bars,
                    "engine": detection.source_engine.value,
                }
            )

        criteria = [
            {
                "criterion": "Motif sur un niveau reel",
                "passed": bool(relations),
                "weight": self.params.weights.level_context,
                "detail": (
                    f"{nearest['kind']} a {nearest['price']} ({nearest['distance_pips']} pip) via "
                    f"{nearest['source']}"
                    if nearest
                    else f"aucun niveau chartiste a moins de {pips(proximity, pip_size):.1f} pips"
                ),
                "counts_towards_confidence": False,
            },
            {
                "criterion": "Formation chartiste active au meme moment",
                "passed": bool(overlapping),
                "weight": self.params.weights.pattern_context,
                "detail": (
                    ", ".join(f"{item['pattern']} ({item['status']}, {item['bars_away']} bougies)" for item in overlapping)
                    if overlapping
                    else "aucune formation chartiste active dans la fenetre de confluence"
                ),
                "counts_towards_confidence": False,
            },
        ]

        payload = {
            "label": label,
            "nearest": nearest,
            "relations": relations[:5],
            "chartist_active": overlapping,
            "trading_signal": False,
            "note": (
                "Contexte informatif : aucun signal, aucun ordre. Un motif isole n'est jamais "
                "presente comme fort par ce moteur."
            ),
        }
        return payload, criteria

    # ------------------------------------------------------------ lifecycle
    def _apply_lifecycle(
        self,
        detection: PatternDetection,
        context: ScanContext,
        existing: PatternDetection | None,
    ) -> None:
        """Move DETECTED -> CONFIRMED / INVALIDATED / EXPIRED on the new closed bars."""
        if existing is not None:
            detection.first_seen_at = existing.first_seen_at
            detection.status = existing.status
            detection.confirmation = existing.confirmation
            detection.invalidation = existing.invalidation
            detection.breakout = existing.breakout

        lifecycle = detection.evidence_points.get("lifecycle") or {}
        state_pattern = bool(lifecycle.get("state_pattern")) if isinstance(lifecycle, dict) else False
        max_bars = lifecycle.get("max_bars_to_confirm") if isinstance(lifecycle, dict) else None

        bars = _bars_from(context.metrics, detection.detected_at_bar_time or 0)

        if state_pattern:
            # a state has no confirmation and no invalidation: it is true or it is over
            detection.last_updated_at = datetime.now(tz=timezone.utc)
            return

        if detection.status is DetectionStatus.DETECTED:
            if not self._confirm(detection, context, bars):
                self._invalidate(detection, context, bars)

        if detection.status is DetectionStatus.DETECTED and isinstance(max_bars, int):
            first_index = bars[0][0] if bars else context.metrics[-1].index
            if context.metrics and (context.metrics[-1].index - first_index) > max_bars:
                detection.status = DetectionStatus.EXPIRED
                detection.notes = detection.notes + [
                    f"expiree : aucune confirmation en {max_bars} bougies"
                ]

        detection.last_updated_at = datetime.now(tz=timezone.utc)

    def _confirm(
        self,
        detection: PatternDetection,
        context: ScanContext,
        bars: list[tuple[int, CandleMetrics]],
    ) -> bool:
        """A confirmation is a real close beyond the trigger by the configured buffer."""
        buffer_ = self.params.globals.confirmation_buffer_pips * context.pip_size
        for level_type, level, direction in _trigger_levels(detection):
            for index, candle in bars:
                broke = (
                    candle.close > level + buffer_
                    if direction == "BULLISH"
                    else candle.close < level - buffer_
                )
                if not broke:
                    continue
                note = (
                    f"cloture {candle.close} au-dessus de {level_type} {level}"
                    if direction == "BULLISH"
                    else f"cloture {candle.close} sous {level_type} {level}"
                )
                detection.status = DetectionStatus.CONFIRMED
                detection.confirmation = ConfirmationInfo(
                    confirmed=True,
                    level=round(level, 10),
                    level_type=level_type,
                    breakout_time=candle.time,
                    breakout_price=candle.close,
                    breakout_candle_time=candle.time,
                    candles_to_confirm=_bars_between(context.metrics, detection.detected_at_bar_time, candle.time),
                    note=note,
                )
                factors = [(f.criterion, f.passed, f.weight, f.detail) for f in detection.confidence_factors]
                factors.append(("Confirmation par cloture", True, self.params.weights.confirmation, note))
                detection.confidence, detection.confidence_factors = score(factors)
                detection.evidence = detection.evidence + [f"CONFIRMATION : {note}"]
                return True
        return False

    def _invalidate(
        self,
        detection: PatternDetection,
        context: ScanContext,
        bars: list[tuple[int, CandleMetrics]],
    ) -> bool:
        level = detection.invalidation.level
        if level is None:
            return False
        buffer_ = self.params.globals.invalidation_buffer_pips * context.pip_size
        direction = detection.direction
        for index, candle in bars:
            broken = (
                candle.close < level - buffer_
                if direction is DetectionDirection.BULLISH
                else candle.close > level + buffer_
            )
            if not broken:
                continue
            detection.status = DetectionStatus.INVALIDATED
            detection.invalidation = detection.invalidation.model_copy(
                update={
                    "invalidated": True,
                    "invalidated_at": candle.time,
                    "reason": (
                        f"cloture {candle.close} "
                        f"{'sous' if direction is DetectionDirection.BULLISH else 'au-dessus de'} "
                        f"{level} ({detection.invalidation.reason or 'niveau depasse'})"
                    ),
                }
            )
            detection.evidence = detection.evidence + [
                f"INVALIDATION : cloture {candle.close} au-dela de {level} a la bougie {index}"
            ]
            return True
        return False

    def _refresh_tracked(
        self,
        symbol: str,
        timeframe: str,
        context: ScanContext,
        fresh_ids: set[str],
        state_ids: dict[tuple[str, str, str], str],
    ) -> list[PatternDetection]:
        """Re-evaluate the live detections of this series on the newest closed bars."""
        refreshed: list[PatternDetection] = []
        for detection in list(self.registry.values()):
            if detection.symbol != symbol or detection.timeframe.value != timeframe:
                continue
            if detection.id in fresh_ids:
                continue

            is_state = detection.pattern in STATE_PATTERNS
            if is_state:
                # a state that is no longer observed has ended
                if detection.status is not DetectionStatus.EXPIRED:
                    detection.status = DetectionStatus.EXPIRED
                    detection.notes = detection.notes + [
                        "etat de marche termine : la structure mesuree n'est plus observee"
                    ]
                    detection.last_updated_at = datetime.now(tz=timezone.utc)
                refreshed.append(detection)
                continue

            if detection.status is DetectionStatus.EXPIRED:
                continue
            self._previous_state[detection.id] = (detection.status, False)
            self._apply_lifecycle(detection, context, detection)
            refreshed.append(detection)

        # superseded states: a new state of the same pattern replaces the old one
        for key, previous_id in list(self._state_active.items()):
            new_id = state_ids.get(key)
            if new_id is None or new_id == previous_id:
                continue
            previous = self.registry.get(previous_id)
            if previous is not None and previous.status is not DetectionStatus.EXPIRED:
                previous.status = DetectionStatus.EXPIRED
                previous.notes = previous.notes + ["etat remplace par un nouvel etat du meme type"]
                previous.last_updated_at = datetime.now(tz=timezone.utc)
                if previous not in refreshed:
                    refreshed.append(previous)
            self._state_active.pop(key, None)
        self._state_active.update(state_ids)
        return refreshed

    # -------------------------------------------------------------- registry
    def commit(self, result: SeriesResult) -> list[LifecycleEvent]:
        """Store the detections and return the state transitions to publish."""
        events: list[LifecycleEvent] = []
        seen: set[str] = set()
        for detection in result.detections:
            seen.add(detection.id)
            self._stale_runs[detection.id] = 0
            previous_status, _ = self._previous_state.get(detection.id, (None, False))
            previous_is_entry = self.registry.get(detection.id) is not None
            self.registry[detection.id] = detection

            if not previous_is_entry:
                events.append(LifecycleEvent("PRICE_ACTION_DETECTED", detection))
                if detection.pattern == "FAILED_BREAKOUT":
                    # distinct event, exactly like BREAKOUT_DETECTED in Phase 2
                    events.append(
                        LifecycleEvent(
                            "FAILED_BREAKOUT",
                            detection,
                            previous_status=DetectionStatus.DETECTED,
                            extra={"failure": _failure_details(detection)},
                        )
                    )
                if detection.status is DetectionStatus.CONFIRMED:
                    events.append(
                        LifecycleEvent("PRICE_ACTION_CONFIRMED", detection, DetectionStatus.DETECTED)
                    )
                continue

            if previous_status is not detection.status:
                if detection.status is DetectionStatus.CONFIRMED:
                    events.append(
                        LifecycleEvent("PRICE_ACTION_CONFIRMED", detection, previous_status)
                    )
                elif detection.status is DetectionStatus.INVALIDATED:
                    events.append(
                        LifecycleEvent("PRICE_ACTION_INVALIDATED", detection, previous_status)
                    )
                elif detection.status is DetectionStatus.EXPIRED:
                    events.append(
                        LifecycleEvent("PRICE_ACTION_EXPIRED", detection, previous_status)
                    )

        self._prune(result, seen)
        self._previous_state.clear()
        return events

    def _prune(self, result: SeriesResult, seen: set[str]) -> None:
        for key, detection in list(self.registry.items()):
            same_series = detection.symbol == result.symbol and detection.timeframe.value == result.timeframe
            if not same_series or key in seen:
                continue
            self._stale_runs[key] = self._stale_runs.get(key, 0) + 1
            if self._stale_runs[key] >= STALE_RUNS_BEFORE_DROP:
                self.registry.pop(key, None)
                self._stale_runs.pop(key, None)

        cap = self.params.globals.max_tracked
        if len(self.registry) > cap:
            ordered = sorted(
                self.registry.values(),
                key=lambda d: (
                    d.status is DetectionStatus.DETECTED,
                    d.last_updated_at or datetime.min.replace(tzinfo=timezone.utc),
                ),
            )
            for detection in ordered[: len(self.registry) - cap]:
                self.registry.pop(detection.id, None)
                self._stale_runs.pop(detection.id, None)
            logger.warning("Price-action registry pruned to %s entries", len(self.registry))

    # ---------------------------------------------------------------- reading
    def all(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        items = list(self.registry.values())
        if symbol:
            items = [d for d in items if d.symbol == normalize_symbol(symbol)]
        if timeframe:
            items = [d for d in items if d.timeframe.value == timeframe.upper()]
        return sorted(items, key=lambda d: (d.detected_at_bar_time or 0, d.symbol), reverse=True)

    def active(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        items = [d for d in self.all(symbol, timeframe) if d.status is DetectionStatus.DETECTED]
        return items

    def structure(self, symbol: str | None = None, timeframe: str | None = None) -> list[PatternDetection]:
        return [d for d in self.all(symbol, timeframe) if d.pattern in STATE_PATTERNS]

    def stats(self) -> dict[str, object]:
        by_status: dict[str, int] = {}
        by_pattern: dict[str, int] = {}
        by_direction: dict[str, int] = {}
        for detection in self.registry.values():
            by_status[detection.status.value] = by_status.get(detection.status.value, 0) + 1
            by_pattern[detection.pattern] = by_pattern.get(detection.pattern, 0) + 1
            by_direction[detection.direction.value] = by_direction.get(detection.direction.value, 0) + 1
        return {
            "engine": ENGINE_NAME,
            "tracked": len(self.registry),
            "by_status": by_status,
            "by_pattern": by_pattern,
            "by_direction": by_direction,
            "parameters_version": self.parameters_version,
        }

    def clear(self) -> None:
        """Test helper."""
        self.registry.clear()
        self._stale_runs.clear()
        self._state_active.clear()
        self._previous_state.clear()

    # -------------------------------------------------------------- confluence
    def confluence_groups(
        self,
        chartist: list[PatternDetection] | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[ConfluenceGroup]:
        """Group what coexists right now: chartist, price action, structure.

        Informative only: no score, no ranking, no signal (see §14 of the brief).
        """
        if not self.params.confluence.enabled:
            return []
        pairs: dict[tuple[str, str], ConfluenceGroup] = {}
        for detection in chartist or []:
            if detection.status is DetectionStatus.EXPIRED:
                continue
            key = (detection.symbol, detection.timeframe.value)
            group = pairs.setdefault(key, ConfluenceGroup(symbol=key[0], timeframe=key[1]))
            group.chartist.append(_group_item(detection))

        for detection in self.registry.values():
            if detection.status is DetectionStatus.EXPIRED:
                continue
            key = (detection.symbol, detection.timeframe.value)
            group = pairs.setdefault(key, ConfluenceGroup(symbol=key[0], timeframe=key[1]))
            if detection.pattern in STATE_PATTERNS:
                group.structure.append(_group_item(detection))
            else:
                group.price_action.append(_group_item(detection))

        for group in pairs.values():
            group.labels = _confluence_labels(group)
        groups = sorted(pairs.values(), key=lambda g: (len(g.chartist) + len(g.price_action), g.symbol), reverse=True)
        if symbol:
            groups = [g for g in groups if g.symbol == normalize_symbol(symbol)]
        if timeframe:
            groups = [g for g in groups if g.timeframe == timeframe.upper()]
        return groups


# ------------------------------------------------- chartist bridge (reuse)
def _levels_from_chartist(
    detections: list[PatternDetection],
    metrics: list[CandleMetrics],
    pip_size: float,
    params: PriceActionParams,
    atr: float,
) -> list[LevelRef]:
    """Real levels of the Phase 2 engine, converted into price-action references.

    Nothing is invented: only the levels the chartist engine already published
    (support, resistance, rectangle edges, channel boundaries, necklines, breakout
    levels). A level far outside the observed price range (more than
    ``levels.context_band_atr`` ATR away) belongs to another regime and is ignored.
    """
    if not metrics:
        return []
    band = params.levels.context_band_atr * atr
    low = min(metric.low for metric in metrics) - band
    high = max(metric.high for metric in metrics) + band
    zone_tolerance = params.levels.zone_tolerance_pips * pip_size
    levels: list[LevelRef] = []
    seen: set[tuple[float, str]] = set()

    for detection in detections:
        if detection.status is DetectionStatus.EXPIRED:
            continue
        age_bars = _age_bars(metrics, detection.detected_at_bar_time)
        for level in detection.drawing.levels:
            if not (low <= level.price <= high):
                continue
            kind = _level_kind_for(level, detection)
            signature = (round(level.price, 6), kind)
            if signature in seen:
                continue
            seen.add(signature)
            levels.append(
                LevelRef(
                    price=level.price,
                    kind=kind,
                    source=f"{detection.pattern} {detection.id} [{level.label}]",
                    source_id=detection.id,
                    tolerance=zone_tolerance if kind in ("RECTANGLE_EDGE", "CHANNEL") else 0.0,
                    last_touch_time=detection.detected_at_bar_time,
                    age_bars=age_bars,
                )
            )
        breakout = detection.breakout
        if breakout is not None:
            signature = (round(breakout.level, 6), "BREAKOUT")
            if signature not in seen and low <= breakout.level <= high:
                seen.add(signature)
                levels.append(
                    LevelRef(
                        price=breakout.level,
                        kind="BREAKOUT",
                        source=f"BREAKOUT {detection.pattern} {detection.id} ({breakout.level_type})",
                        source_id=detection.id,
                        tolerance=zone_tolerance,
                        last_touch_time=breakout.breakout_time,
                        age_bars=_age_bars(metrics, breakout.breakout_time),
                    )
                )
    levels.sort(key=lambda item: item.age_bars if item.age_bars is not None else 10**9)
    return levels[:40]


def _level_kind_for(level, detection: PatternDetection) -> str:
    if detection.pattern == "RECTANGLE":
        return "RECTANGLE_EDGE"
    kind = (getattr(level, "kind", "") or "").upper()
    if kind in ("SUPPORT", "RESISTANCE", "CHANNEL", "NECKLINE", "TRENDLINE"):
        return kind
    if detection.pattern in ("SUPPORT", "RESISTANCE"):
        return detection.pattern
    return "CHARTIST_BOUNDARY"


def _breakouts_from_chartist(
    detections: list[PatternDetection], metrics: list[CandleMetrics]
) -> list[BreakoutRef]:
    """Confirmed breakouts of the Phase 2 engine: the price-action engine never
    recomputes a breakout, it consumes this list (see FAILED_BREAKOUT)."""
    if not metrics:
        return []
    first_time = metrics[0].time
    references: list[BreakoutRef] = []
    for detection in detections:
        breakout = detection.breakout
        if breakout is None or breakout.breakout_time < first_time:
            continue
        references.append(
            BreakoutRef(
                level=breakout.level,
                level_type=breakout.level_type,
                direction=breakout.direction.value,
                breakout_time=breakout.breakout_time,
                breakout_price=breakout.breakout_price,
                parent_pattern=detection.pattern,
                parent_id=detection.id,
                retested=breakout.retested,
                retest_time=detection.retest.retest_candle_time if detection.retest else None,
                retest_price=detection.retest.retest_price if detection.retest else None,
            )
        )
    return references


def _age_bars(metrics: list[CandleMetrics], time_value: int | None) -> int | None:
    if time_value is None:
        return None
    index = _index_of_time(metrics, time_value)
    return None if index is None else metrics[-1].index - index


def _bars_between(metrics: list[CandleMetrics], start_time: int | None, end_time: int) -> int:
    if start_time is None:
        return 0
    start = _index_of_time(metrics, start_time)
    end = _index_of_time(metrics, end_time)
    if start is None or end is None:
        return 0
    return max(0, end - start)


# ------------------------------------------------------------------- helpers
def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _index_of_time(metrics: list[CandleMetrics], time_value: int) -> int | None:
    for metric in metrics:
        if metric.time == time_value:
            return metric.index
    return None


def _candidate_zone(candidate: Candidate) -> tuple[float, float]:
    """Price zone of a candidate, read from the levels it declared."""
    prices = [float(price) for price in candidate.levels.values()]
    if not prices:
        for pivot in (candidate.evidence_points.get("pivots") or {}).values():
            price = pivot.get("price") if isinstance(pivot, dict) else None
            if price is not None:
                prices.append(float(price))
    if not prices:
        return 0.0, 0.0
    return min(prices), max(prices)


def _distance_to_zone(price: float, zone_low: float, zone_high: float) -> float:
    if zone_low <= price <= zone_high:
        return 0.0
    return min(abs(price - zone_low), abs(price - zone_high))


def _same_side(level: float, zone_low: float, zone_high: float, direction: str) -> bool:
    """Is the level on the side that makes the pattern's direction meaningful?

    A bullish pattern above a support is a different message from the same pattern
    below a resistance; the payload keeps that information explicit.
    """
    if direction == "BULLISH":
        return level <= zone_high
    if direction == "BEARISH":
        return level >= zone_low
    return True


def _bars_from(metrics: list[CandleMetrics], start_time: int) -> list[tuple[int, CandleMetrics]]:
    for offset, metric in enumerate(metrics):
        if metric.time >= start_time:
            return [(metric.index, item) for item in metrics[offset:]]
    return []


def _trigger_levels(detection: PatternDetection) -> list[tuple[str, float, str]]:
    """Confirmation levels, read from the payload (no hidden state).

    Only a break in the direction of the pattern can confirm it; NEUTRAL patterns
    (outside bar, inside bar, doji) keep both sides, each with its own direction.
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


def _failure_details(detection: PatternDetection) -> dict[str, object]:
    points = detection.evidence_points or {}
    return {
        "breakout_level": points.get("breakout_level"),
        "breakout_candle": points.get("breakout_candle"),
        "failure_candle": points.get("failure_candle"),
        "return_price": points.get("return_price"),
        "direction": detection.direction.value,
        "measurements": (points.get("measurements") or {}) if isinstance(points.get("measurements"), dict) else {},
    }


def _group_item(detection: PatternDetection) -> dict[str, object]:
    return {
        "id": detection.id,
        "pattern": detection.pattern,
        "direction": detection.direction.value,
        "status": detection.status.value,
        "confidence": detection.confidence,
        "detected_at_bar_time": detection.detected_at_bar_time,
        "engine": detection.source_engine.value,
        "category": detection.category.value,
    }


def _confluence_labels(group: ConfluenceGroup) -> list[str]:
    labels: list[str] = []
    if group.chartist and group.price_action:
        labels.append("STRUCTURE_CHARTISTE_ET_PRICE_ACTION_SIMULTANEES")
    if group.structure:
        labels.append("CONTEXTE_DE_MARCHE_MESURE")
    if not group.price_action:
        labels.append("AUCUN_MOTIF_PRICE_ACTION_ACTIF")
    return labels


__all__ = [
    "PriceActionEngine",
    "SeriesResult",
    "LifecycleEvent",
    "dedup_key",
    "detectors",
    "STATE_PATTERNS",
]
