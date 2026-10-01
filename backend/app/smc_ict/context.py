"""Shared measurement layer of the SMC/ICT engine.

Everything a detector needs to *measure* lives here, so no detector invents its
own arithmetic:

* ``build_context`` assembles a :class:`ScanContext` from real candles;
* ``find_smc_swings`` reuses the Phase 1/2 pivot detector and adds the
  measurable ``strength``;
* ``atr`` is the same ATR(period) used by the other engines;
* ``dominant_structure`` derives the prevailing direction from the labelled
  swings (HH/HL vs LH/LL) - it never guesses.
"""

from __future__ import annotations

from app.instruments import normalize_symbol
from app.price_action.candles import CandleMetrics, measure_all
from app.schemas.market import Candle, CandleSeries
from app.schemas.structure import SwingKind, SwingPoint
from app.services.structure import find_swings
from app.smc_ict.models import ScanContext, SmcSwing
from app.smc_ict.params import SmcIctParams


# ------------------------------------------------------------------------ ATR
def average_true_range(metrics: list[CandleMetrics], period: int) -> float:
    """Wilder-style ATR over closed bars (0.0 when there is not enough data)."""
    if len(metrics) < 2 or period < 1:
        return 0.0
    window = metrics[-(period + 1):]
    ranges: list[float] = []
    for previous, current in zip(window, window[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if not ranges:
        return 0.0
    return sum(ranges) / len(ranges)


def structural_atr(metrics: list[CandleMetrics], params: SmcIctParams) -> float:
    """The volatility scale used to size every threshold.

    The slow ATR is preferred (it does not jump on a single bar); the fast ATR is
    the fallback when the window is too short.
    """
    slow = average_true_range(metrics, params.global_.atr_slow_period)
    if slow > 0:
        return slow
    return average_true_range(metrics, params.global_.atr_period)


# --------------------------------------------------------------------- swings
def swing_strength(
    metrics: list[CandleMetrics],
    index: int,
    kind: SwingKind,
    params: SmcIctParams,
) -> tuple[int, int, int, float]:
    """Return ``(strength, dominance_left, dominance_right, prominence)``.

    Measurable, reproducible: count the bars each side the pivot dominates, then
    add one point per ``atr_scale`` ATR of prominence over the surrounding
    extremes. A flat market gives 0.
    """
    bar = metrics[index]
    dominance = params.swings.dominance_bars
    left_span = range(max(0, index - dominance), index)
    right_span = range(index + 1, min(len(metrics), index + dominance + 1))

    def dominates(other: CandleMetrics) -> bool:
        return bar.high > other.high if kind is SwingKind.HIGH else bar.low < other.low

    dominance_left = sum(1 for i in left_span if dominates(metrics[i]))
    dominance_right = sum(1 for i in right_span if dominates(metrics[i]))

    neighbours = [metrics[i] for i in list(left_span) + list(right_span)]
    if neighbours:
        if kind is SwingKind.HIGH:
            prominence = bar.high - max(item.high for item in neighbours)
        else:
            prominence = min(item.low for item in neighbours) - bar.low
    else:
        prominence = 0.0
    prominence = max(0.0, prominence)

    atr = structural_atr(metrics, params)
    atr_points = int(prominence / (params.swings.atr_scale * atr)) if atr > 0 else 0
    strength = dominance_left + dominance_right + atr_points
    return strength, dominance_left, dominance_right, prominence


def find_smc_swings(metrics: list[CandleMetrics], params: SmcIctParams) -> list[SmcSwing]:
    """Confirmed swings, oldest first, each with its measurable strength.

    The pivots themselves come from Phase 1/2 (``find_swings``), converted to the
    model used by the chart engine: no second pivot detector exists.
    """
    candles = [
        Candle(time=bar.time, open=bar.open, high=bar.high, low=bar.low, close=bar.close)
        for bar in metrics
    ]
    pivots: list[SwingPoint] = find_swings(
        candles, left=params.global_.pivot_left, right=params.global_.pivot_right
    )
    swings: list[SmcSwing] = []
    for pivot in pivots[-params.global_.max_swings:]:
        strength, left, right, prominence = swing_strength(
            metrics, pivot.index, pivot.kind, params
        )
        swings.append(
            SmcSwing(
                index=pivot.index,
                time=pivot.time,
                price=pivot.price,
                kind=pivot.kind,
                strength=strength,
                confirmed_at_index=pivot.confirmed_at_index,
                dominance_left=left,
                dominance_right=right,
                prominence=prominence,
            )
        )
    return swings


# ------------------------------------------------------------------- structure
def dominant_structure(swings: list[SmcSwing], min_swings: int) -> tuple[str, str]:
    """Prevailing direction and the reason for it.

    Returns ``(direction, reason)`` with direction in BULLISH / BEARISH /
    UNKNOWN. Built from the last labelled swings (higher highs + higher lows =
    bullish), never from a guess.
    """
    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]
    if len(highs) < 2 or len(lows) < 2 or len(swings) < min_swings:
        return "UNKNOWN", f"{len(swings)} swing(s) confirmés, minimum {min_swings} requis"

    last_highs, last_lows = highs[-2:], lows[-2:]
    higher_high = last_highs[1].price > last_highs[0].price
    higher_low = last_lows[1].price > last_lows[0].price
    lower_high = last_highs[1].price < last_highs[0].price
    lower_low = last_lows[1].price < last_lows[0].price

    if higher_high and higher_low:
        return "BULLISH", (
            f"sommets croissants ({last_highs[0].price:.5f} -> {last_highs[1].price:.5f}) et "
            f"creux croissants ({last_lows[0].price:.5f} -> {last_lows[1].price:.5f})"
        )
    if lower_high and lower_low:
        return "BEARISH", (
            f"sommets décroissants ({last_highs[0].price:.5f} -> {last_highs[1].price:.5f}) et "
            f"creux décroissants ({last_lows[0].price:.5f} -> {last_lows[1].price:.5f})"
        )
    return "RANGE", (
        f"structure mixte : sommets {last_highs[0].price:.5f}/{last_highs[1].price:.5f}, "
        f"creux {last_lows[0].price:.5f}/{last_lows[1].price:.5f}"
    )


def last_swing(swings: list[SmcSwing], kind: SwingKind, before_index: int | None = None) -> SmcSwing | None:
    """Most recent swing of that kind, optionally strictly before an index."""
    candidates = [s for s in swings if s.kind is kind]
    if before_index is not None:
        candidates = [s for s in candidates if s.index < before_index]
    return candidates[-1] if candidates else None


def build_context(
    series: CandleSeries,
    params: SmcIctParams,
    pip_size: float,
    digits: int = 5,
) -> ScanContext:
    """Assemble a :class:`ScanContext` from a real series.

    The metrics are the Phase 3 ones (:func:`app.price_action.candles.measure_all`):
    the same geometry, the same rounding, so both engines describe a candle
    identically.
    """
    metrics = measure_all(list(series.candles))
    atr = structural_atr(metrics, params)
    swings = tuple(find_smc_swings(metrics, params))
    return ScanContext(
        symbol=normalize_symbol(series.symbol),
        timeframe=series.timeframe.value,
        metrics=metrics,
        params=params,
        atr=atr,
        pip_size=pip_size,
        digits=digits,
        swings=swings,
    )
