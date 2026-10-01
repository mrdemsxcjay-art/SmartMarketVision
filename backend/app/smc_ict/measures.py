"""Measured helpers shared by the SMC/ICT detectors.

Nothing here interprets: every function returns numbers taken from the real
OHLC (the same candle metrics the price-action engine uses).
"""

from __future__ import annotations

from app.price_action.candles import CandleMetrics, ge, gt, le, lt
from app.smc_ict.models import ScanContext, SmcSwing


def displacement_of(
    ctx: ScanContext,
    index: int,
    lookback: int | None = None,
) -> dict[str, object]:
    """Objective displacement measurements ending on bar ``index``.

    Returns the range (pips / ATR), the body ratio, the net move, the total
    travelled distance and the resulting trace efficiency, the progression of
    the close beyond the previous candle's extreme, plus the number of
    consecutive bars moving in the same direction. A "big candle" is never
    claimed: only these numbers are.
    """
    params = ctx.params.displacement
    lookback = lookback or params.lookback_bars
    start = max(0, index - lookback + 1)
    bars = [ctx.metrics[i] for i in range(start, index + 1)]
    bar = ctx.metrics[index]
    if not bars:
        return {}

    net_move = bar.close - bars[0].open
    travelled = sum(abs(item.close - item.open) for item in bars)
    efficiency = abs(net_move) / travelled if travelled > 0 else 0.0
    direction = "BULLISH" if net_move > 0 else ("BEARISH" if net_move < 0 else "NEUTRAL")

    streak = 0
    for item in reversed(bars):
        is_bull = item.close > item.open
        if (direction == "BULLISH" and is_bull) or (direction == "BEARISH" and not is_bull):
            streak += 1
        else:
            break

    previous = ctx.metrics[index - 1] if index > 0 else None
    if previous is None:
        progression = 0.0
        previous_extreme = bar.close
    elif bar.close >= bar.open:            # bullish candle: must take out the previous high
        previous_extreme = previous.high
        progression = bar.close - previous.high
    else:                                   # bearish candle: must take out the previous low
        previous_extreme = previous.low
        progression = previous.low - bar.close

    return {
        "range_pips": round(ctx.pips(bar.range), 2),
        "range_atr": round(ctx.atr_multiple(bar.range), 4),
        "body_ratio": round(bar.body_ratio, 4),
        "net_move_pips": round(ctx.pips(net_move), 2),
        "net_move_atr": round(ctx.atr_multiple(net_move), 4),
        "efficiency": round(efficiency, 4),
        "same_direction_bars": streak,
        "progression_pips": round(ctx.pips(progression), 2),
        "progression_atr": round(ctx.atr_multiple(progression), 4),
        "previous_extreme": round(previous_extreme, 8),
        "took_out_previous_extreme": bool(progression > 0),
        "from_index": start,
        "to_index": index,
        "direction": direction,
        "atr": round(ctx.atr, 8),
    }


def is_displacement(ctx: ScanContext, index: int) -> tuple[bool, dict[str, object]]:
    """Apply the declared displacement thresholds to one bar."""
    params = ctx.params.displacement
    measures = displacement_of(ctx, index)
    if not measures:
        return False, {}
    threshold = ctx.min_size(params.min_range_pips, params.min_range_atr)
    progression_floor = ctx.min_size(params.min_progression_pips, params.min_progression_atr)
    bar = ctx.metrics[index]
    passed = (
        ge(bar.range, threshold)
        and ge(float(measures["body_ratio"]), params.min_body_ratio)
        and ge(float(measures["progression_pips"]), ctx.pips(progression_floor))
    )
    measures["progression_floor_pips"] = round(ctx.pips(progression_floor), 2)
    measures["threshold"] = round(threshold, 8)
    measures["threshold_rule"] = (
        f"max({params.min_range_pips} pips, {params.min_range_atr} ATR) = {threshold:.5f}"
    )
    return passed, measures


def swing_after(swings: tuple[SmcSwing, ...], index: int) -> SmcSwing | None:
    """Most recent swing confirmed at or before ``index``."""
    candidates = [s for s in swings if s.confirmed_at_index <= index]
    return candidates[-1] if candidates else None


def last_confirmed_swing(swings: tuple[SmcSwing, ...], is_high: bool) -> SmcSwing | None:
    """Most recent confirmed swing of the requested kind."""
    filtered = [s for s in swings if s.is_high is is_high]
    return filtered[-1] if filtered else None


def bars_between(ctx: ScanContext, start_index: int, end_index: int) -> int:
    return max(0, end_index - start_index)


def price_side(price: float, level: float) -> str:
    """Which side of a level a price sits on (never 'close enough')."""
    return "ABOVE" if gt(price, level) else ("BELOW" if lt(price, level) else "AT")


def touched(ctx: ScanContext, index: int, low: float, high: float) -> bool:
    """True when the candle of ``index`` traded inside ``[low, high]``."""
    bar = ctx.metrics[index]
    return barley_overlaps(bar, low, high)


def barley_overlaps(bar: CandleMetrics, low: float, high: float) -> bool:
    return not (lt(bar.high, low) or gt(bar.low, high))


def closed_inside(bar: CandleMetrics, low: float, high: float) -> bool:
    return not (lt(bar.close, low) or gt(bar.close, high))


def overlap_size(bar: CandleMetrics, low: float, high: float) -> float:
    """How much of the candle range sits inside ``[low, high]`` (price units)."""
    top = min(bar.high, high)
    bottom = max(bar.low, low)
    return max(0.0, top - bottom)


def partial_share(bar: CandleMetrics, low: float, high: float) -> float:
    """Share of the band axis the candle covered (0..1)."""
    band = high - low
    if le(band, 0.0):
        return 0.0
    return min(1.0, overlap_size(bar, low, high) / band)
