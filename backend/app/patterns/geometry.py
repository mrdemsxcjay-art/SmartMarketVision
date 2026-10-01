"""Line fitting, touch counting and level clustering.

All maths operate on real pivot coordinates (bar index + real price). Bar index
is used for the regression so the slope is not distorted by weekend gaps; the
conversion to price/second is available for display.
"""

from __future__ import annotations

from statistics import mean

from app.patterns.models import Pivot, TrendLine


def fit_line(pivots: list[Pivot], kind: str) -> TrendLine | None:
    """Least-squares line through pivots (index -> price)."""
    if len(pivots) < 2:
        return None
    xs = [float(p.index) for p in pivots]
    ys = [p.price for p in pivots]
    n = len(xs)
    mean_x, mean_y = mean(xs), mean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        slope = 0.0
    else:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x

    # coefficient of determination, used to reject noisy "lines"
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)

    ordered = sorted(pivots, key=lambda p: p.index)
    return TrendLine(
        start_index=ordered[0].index,
        end_index=ordered[-1].index,
        slope_per_bar=slope,
        intercept=intercept,
        kind=kind,
        pivots=ordered,
        r2=r2,
    )


def count_touches(
    line: TrendLine,
    pivots: list[Pivot],
    *,
    kind: str,
    tolerance: float,
    start_index: int | None = None,
    end_index: int | None = None,
) -> list[Pivot]:
    """Pivots whose price sits within ``tolerance`` of the line."""
    start = line.start_index if start_index is None else start_index
    end = line.end_index if end_index is None else end_index
    touches: list[Pivot] = []
    for pivot in pivots:
        if pivot.kind != kind or pivot.index < start or pivot.index > end:
            continue
        if abs(pivot.price - line.value_at(pivot.index)) <= tolerance:
            touches.append(pivot)
    return touches


def with_touches(line: TrendLine, touches: list[Pivot]) -> TrendLine:
    line.touches = len(touches)
    line.touch_indices = [p.index for p in touches]
    return line


def slopes_converging(upper: TrendLine, lower: TrendLine) -> bool:
    """True when the two lines approach each other going forward."""
    return upper.slope_per_bar < lower.slope_per_bar


def apex_index(upper: TrendLine, lower: TrendLine) -> int | None:
    """Bar index where the two lines meet, or None when parallel."""
    delta_slope = lower.slope_per_bar - upper.slope_per_bar
    if abs(delta_slope) < 1e-12:
        return None
    intersection = (upper.intercept - lower.intercept) / delta_slope
    return int(round(intersection))


def width_at(upper: TrendLine, lower: TrendLine, index: int) -> float:
    return abs(upper.value_at(index) - lower.value_at(index))


def relative_slope_gap(first: TrendLine, second: TrendLine, atr: float, fallback: float = 1e-9) -> float:
    """|s1 - s2| normalised by the largest of (|s1|, |s2|, intra-bar ATR scale)."""
    scale = max(abs(first.slope_per_bar), abs(second.slope_per_bar), atr * 0.01, fallback)
    return abs(first.slope_per_bar - second.slope_per_bar) / scale


def midpoint_slope(candles) -> float:
    """Least-squares slope (price per bar) through the bars' midpoints.

    Used to measure how much a box drifts when its internal pivots are too few to
    fit two boundary lines. A regression is robust to the first pullback bar,
    which a plain first-vs-last difference is not.
    """
    n = len(candles)
    if n < 2:
        return 0.0
    mids = [(c.high + c.low) / 2 for c in candles]
    mean_x = (n - 1) / 2
    mean_y = sum(mids) / n
    covariance = sum((i - mean_x) * (mids[i] - mean_y) for i in range(n))
    variance = sum((i - mean_x) ** 2 for i in range(n))
    return covariance / variance if variance else 0.0


def cluster_levels(
    pivots: list[Pivot],
    *,
    tolerance: float,
    kind: str,
    min_touches: int,
) -> list[dict[str, object]]:
    """Group pivots of one kind whose prices are within ``tolerance``.

    Returns clusters sorted by touch count (highest first). ``price`` is the mean
    of the touches, ``first_touch``/``last_touch`` are real pivot times.
    """
    candidates = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.price)
    clusters: list[list[Pivot]] = []
    for pivot in candidates:
        placed = False
        for cluster in clusters:
            reference = mean(p.price for p in cluster)
            if abs(pivot.price - reference) <= tolerance:
                cluster.append(pivot)
                placed = True
                break
        if not placed:
            clusters.append([pivot])

    result: list[dict[str, object]] = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        ordered = sorted(cluster, key=lambda p: p.index)
        result.append(
            {
                "price": mean(p.price for p in ordered),
                "touch_count": len(ordered),
                "first_touch": ordered[0].time,
                "first_touch_index": ordered[0].index,
                "last_touch": ordered[-1].time,
                "last_touch_index": ordered[-1].index,
                "kind": kind,
                "pivots": ordered,
                "spread": max(p.price for p in ordered) - min(p.price for p in ordered),
            }
        )
    result.sort(key=lambda item: (-int(item["touch_count"]), -int(item["last_touch_index"])))
    return result
