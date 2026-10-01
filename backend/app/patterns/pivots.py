"""Pivot detection, ATR and shared numeric helpers.

Deterministic, no look-ahead: a pivot at bar ``i`` needs ``right`` *following*
bars, so ``confirmed_at_index = i + right`` and a detector may only use pivots
whose confirmation bar is already closed.
"""

from __future__ import annotations

from app.patterns.models import BarContext, Pivot
from app.schemas.market import Candle


def compute_atr(candles: list[Candle], period: int = 14) -> float:
    """Average True Range (Wilder) over real OHLC.

    Returns 0.0 when there is not enough data - callers then fall back to the
    absolute pip thresholds only.
    """
    if len(candles) < 2:
        return 0.0
    true_ranges: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    if not true_ranges:
        return 0.0
    if len(true_ranges) <= period:
        return sum(true_ranges) / len(true_ranges)
    # Wilder: seed with the first N true ranges, then smooth the rest
    atr = sum(true_ranges[:period]) / period
    for value in true_ranges[period:]:
        atr = (atr * (period - 1) + value) / period
    return atr


def find_pivots(candles: list[Candle], left: int = 2, right: int = 2) -> list[Pivot]:
    """Strict pivot highs/lows, oldest first.

    Strict inequality means equal highs/lows never produce a pivot: the engine
    prefers missing a pivot over inventing one.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    pivots: list[Pivot] = []
    if len(candles) < left + right + 1:
        return pivots

    for index in range(left, len(candles) - right):
        bar = candles[index]
        window = candles[index - left : index + right + 1]
        others = [c for c in window if c is not bar]
        if all(bar.high > other.high for other in others):
            pivots.append(Pivot(index, bar.time, bar.high, "HIGH", index + right))
        elif all(bar.low < other.low for other in others):
            pivots.append(Pivot(index, bar.time, bar.low, "LOW", index + right))

    pivots.sort(key=lambda p: (p.index, 0 if p.is_high else 1))
    return pivots


def alternate(pivots: list[Pivot]) -> list[Pivot]:
    """Collapse consecutive same-kind pivots, keeping the most extreme.

    Pattern geometry (necklines, trendlines) only makes sense on an alternating
    H/L sequence; keeping both highs of a double-high would double-count touches.
    """
    result: list[Pivot] = []
    for pivot in pivots:
        if result and result[-1].kind == pivot.kind:
            previous = result[-1]
            better = (
                pivot.price > previous.price if pivot.is_high else pivot.price < previous.price
            )
            if better:
                result[-1] = pivot
            continue
        result.append(pivot)
    return result


def build_context(
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    digits: int,
    pip_size: float,
    left: int,
    right: int,
    atr_period: int,
    max_pivots: int,
    atr_slow_period: int = 100,
) -> BarContext:
    """Prepare the analysis context from closed candles only.

    Two ATRs are exposed because they answer two different questions:
    * ``atr`` (short, default 14) - how volatile the instrument is *right now*,
      used for slope thresholds;
    * ``atr_slow`` (long, default 100) - the volatility scale of the structure
      being analysed. Sizing a pattern with the current ATR would break inside a
      quiet consolidation (the ATR would collapse and nothing could ever qualify).
    """
    closed = [candle for candle in candles if candle.closed]
    pivots = alternate(find_pivots(closed, left=left, right=right))
    return BarContext(
        symbol=symbol,
        timeframe=timeframe,
        candles=closed,
        digits=digits,
        pip_size=pip_size,
        atr=compute_atr(closed, period=atr_period),
        atr_slow=compute_atr(closed, period=atr_slow_period),
        pivots=pivots[-max_pivots:] if max_pivots else pivots,
    )


def pips(price_delta: float, pip_size: float) -> float:
    """Convert a price difference to pips (absolute value)."""
    return abs(price_delta) / pip_size if pip_size else 0.0


def size_threshold(
    min_pips: float, atr_fraction: float, pip_size: float, atr: float
) -> float:
    """Adaptive threshold: max(absolute floor in pips, ATR fraction).

    Using the max keeps the engine strict on quiet instruments and still
    meaningful on volatile ones.
    """
    return max(min_pips * pip_size, atr_fraction * atr)


def last_pivot_of(pivots: list[Pivot], kind: str) -> Pivot | None:
    for pivot in reversed(pivots):
        if pivot.kind == kind:
            return pivot
    return None


def pivots_between(pivots: list[Pivot], start_index: int, end_index: int) -> list[Pivot]:
    return [p for p in pivots if start_index < p.index < end_index]
