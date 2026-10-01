"""Generic market-structure layer (Phase 1).

Scope, stated explicitly:
* detected here: swing highs, swing lows and their HH / HL / LH / LL labels
  plus a structural trend (BULLISH / BEARISH / RANGE / UNDEFINED);
* NOT detected here: BOS, CHoCH, order blocks, FVG, liquidity zones.
  Those are SMC/ICT concepts reserved for a later phase. Nothing in this module
  claims an SMC/ICT reading.

Only *closed* candles are used by default, so the structure cannot repaint
because of the still-forming bar.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.instruments import get_symbol_info, normalize_symbol
from app.schemas.market import Candle, Timeframe, as_timeframe
from app.schemas.structure import (
    StructuralTrend,
    StructureAnalysis,
    SwingKind,
    SwingLabel,
    SwingPoint,
)

DEFAULT_PIVOT_LEFT = 2
DEFAULT_PIVOT_RIGHT = 2


def find_swings(
    candles: list[Candle],
    left: int = DEFAULT_PIVOT_LEFT,
    right: int = DEFAULT_PIVOT_RIGHT,
) -> list[SwingPoint]:
    """Return confirmed pivots, oldest first.

    A pivot high needs ``high[i]`` strictly greater than the ``left`` bars
    before it and the ``right`` bars after it (the same logic inverted for a
    pivot low). Strict inequality means equal highs/lows produce no pivot
    instead of an arbitrary one.

    ``confirmed_at_index = i + right``: the pivot is only knowable once ``right``
    following bars have printed, which is what keeps the analysis repaint-free.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    swings: list[SwingPoint] = []
    if len(candles) < left + right + 1:
        return swings

    for i in range(left, len(candles) - right):
        window = candles[i - left : i + right + 1]
        bar = candles[i]
        if all(bar.high > other.high for other in window if other is not bar):
            swings.append(
                SwingPoint(
                    index=i,
                    time=bar.time,
                    price=bar.high,
                    kind=SwingKind.HIGH,
                    confirmed_at_index=i + right,
                )
            )
        elif all(bar.low < other.low for other in window if other is not bar):
            swings.append(
                SwingPoint(
                    index=i,
                    time=bar.time,
                    price=bar.low,
                    kind=SwingKind.LOW,
                    confirmed_at_index=i + right,
                )
            )

    swings.sort(key=lambda s: (s.index, 0 if s.kind is SwingKind.HIGH else 1))
    return swings


def label_swings(swings: list[SwingPoint]) -> list[SwingPoint]:
    """Label each pivot HH / HL / LH / LL versus the previous pivot of the same kind."""
    previous_high: SwingPoint | None = None
    previous_low: SwingPoint | None = None
    for swing in swings:
        if swing.kind is SwingKind.HIGH:
            if previous_high is None:
                swing.label = SwingLabel.FIRST_HIGH
            elif swing.price > previous_high.price:
                swing.label = SwingLabel.HIGHER_HIGH
            elif swing.price < previous_high.price:
                swing.label = SwingLabel.LOWER_HIGH
            else:
                # Exact equality: carry the previous label instead of inventing one.
                swing.label = previous_high.label
            previous_high = swing
        else:
            if previous_low is None:
                swing.label = SwingLabel.FIRST_LOW
            elif swing.price > previous_low.price:
                swing.label = SwingLabel.HIGHER_LOW
            elif swing.price < previous_low.price:
                swing.label = SwingLabel.LOWER_LOW
            else:
                swing.label = previous_low.label
            previous_low = swing
    return swings


def classify_trend(swings: list[SwingPoint], min_swings: int = 4) -> tuple[StructuralTrend, list[str]]:
    """Structural trend from the last two highs and the last two lows."""
    notes: list[str] = []
    highs = [s for s in swings if s.kind is SwingKind.HIGH]
    lows = [s for s in swings if s.kind is SwingKind.LOW]

    if len(swings) < min_swings or len(highs) < 2 or len(lows) < 2:
        notes.append(
            f"not enough confirmed pivots ({len(highs)} highs / {len(lows)} lows) "
            f"- need at least 2 of each"
        )
        return StructuralTrend.UNDEFINED, notes

    last_high, prev_high = highs[-1], highs[-2]
    last_low, prev_low = lows[-1], lows[-2]

    higher_high = last_high.price > prev_high.price
    lower_high = last_high.price < prev_high.price
    higher_low = last_low.price > prev_low.price
    lower_low = last_low.price < prev_low.price

    if higher_high and higher_low:
        return StructuralTrend.BULLISH, notes
    if lower_high and lower_low:
        return StructuralTrend.BEARISH, notes
    if (higher_high and lower_low) or (lower_high and higher_low):
        notes.append("last high and last low move in opposite directions - expansion / contraction")
        return StructuralTrend.RANGE, notes
    if not (higher_high or lower_high or higher_low or lower_low):
        notes.append("last pivots are equal to the previous ones - flat structure")
        return StructuralTrend.RANGE, notes

    notes.append("mixed pivot sequence - structure not directional")
    return StructuralTrend.UNDEFINED, notes


def analyse_structure(
    symbol: str,
    timeframe: Timeframe | str,
    candles: list[Candle],
    left: int = DEFAULT_PIVOT_LEFT,
    right: int = DEFAULT_PIVOT_RIGHT,
    closed_only: bool = True,
) -> StructureAnalysis:
    """Full Phase-1 structure read for one symbol/timeframe."""
    code = normalize_symbol(symbol)
    tf = as_timeframe(timeframe)
    info = get_symbol_info(code)

    notes: list[str] = []
    used = candles
    if closed_only:
        closed = [c for c in candles if c.closed]
        if len(closed) != len(candles):
            notes.append("the still-forming candle is excluded from the structure read")
        used = closed

    swings = label_swings(find_swings(used, left=left, right=right))
    trend, trend_notes = classify_trend(swings)
    notes.extend(trend_notes)

    highs = [s for s in swings if s.kind is SwingKind.HIGH]
    lows = [s for s in swings if s.kind is SwingKind.LOW]

    if info is None:
        notes.append(f"'{code}' is not in the instrument catalog")

    return StructureAnalysis(
        symbol=code,
        timeframe=tf,
        trend=trend,
        labels=[s.label for s in swings],
        swings=swings,
        last_swing_high=highs[-1] if highs else None,
        last_swing_low=lows[-1] if lows else None,
        bars_analyzed=len(used),
        pivot_left=left,
        pivot_right=right,
        evaluated_at=datetime.now(tz=timezone.utc),
        using_closed_candles_only=closed_only,
        notes=notes,
    )


def recent_labels(structure: StructureAnalysis, count: int = 4) -> list[str]:
    """Short label sequence for the dashboard, e.g. ``['HH', 'HL', 'HH', 'HL']``."""
    labels = [s.label.value for s in structure.swings if s.label.value not in {"H", "L", "?"}]
    return labels[-count:]
