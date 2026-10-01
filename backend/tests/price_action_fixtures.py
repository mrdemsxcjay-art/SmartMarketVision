"""Controlled OHLC fixtures for the price-action engine - TEST FIXTURES ONLY.

Nothing here is ever imported by the application: the production path only reads
real provider data. Each builder starts from a *calm* backdrop that cannot match
any price-action rule (alternating equal bodies, no engulfing coverage, symmetric
wicks), then appends the exact bars of the pattern under test, so every
measurement can be recomputed by hand from the numbers written here.

The calm backdrop is a series of **sub-pip bars** (body 0.4 pip, wick 0.2 pip,
alternating direction), i.e. below every absolute anti-noise floor the engine
enforces:

* engulfing    -> previous body 0.4 pip < ``min_previous_body_pips`` (1 pip)
* pin bar      -> range 0.8 pip     < ``min_range_pips`` (4 pips)
* doji / inside-> range 0.8 pip     < ``min_range_pips`` (3 and 4 pips)
* outside bar  -> range 0.8 pip     < ``min_range_pips`` (4 pips)
* impulsion    -> move << ``impulse_min_move_pips`` (15 pips)
* consolidation-> compression = 1.00 > ``consolidation_max_compression`` (0.6)

So a fixture = calm backdrop + the exact bars under test, and "no pattern found"
really means "the rule under test rejected it", not "another bar happened to
match first".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.market import Candle, CandleSeries, Timeframe

PIP = 0.0001
BASE = 1.1000
START = 1_760_000_000  # fixed anchor: the fixtures are fully reproducible
TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def px(pips: float) -> float:
    """Price 1.1000 + ``pips`` pips, rounded like a real 5-digit quote."""
    return round(BASE + pips * PIP, 5)


@dataclass
class BarSpec:
    """One bar, written in pips relative to :data:`BASE` (readable by a human)."""

    open: float
    high: float
    low: float
    close: float

    def build(self, index: int, timeframe: str = "M15") -> Candle:
        return Candle(
            time=START + index * TF_SECONDS[timeframe],
            open=px(self.open),
            high=px(self.high),
            low=px(self.low),
            close=px(self.close),
            volume=None,  # the real Forex feed has no volume: never invented
            closed=True,
        )


def calm_bars(count: int, *, body: float = 0.4, wick: float = 0.2, start: float = 0.0) -> list[BarSpec]:
    """``count`` bars that match no price-action rule (see the module docstring)."""
    bars: list[BarSpec] = []
    for step in range(count):
        if step % 2 == 0:  # bullish: open low, close high
            open_, close = start, start + body
        else:  # bearish: back to the same level, so the range never drifts
            open_, close = start + body, start
        bars.append(
            BarSpec(
                open=open_,
                high=max(open_, close) + wick,
                low=min(open_, close) - wick,
                close=close,
            )
        )
    return bars


def series(bars: list[BarSpec], *, symbol: str = "EURUSD", timeframe: str = "M15") -> CandleSeries:
    return CandleSeries(
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        provider="fixture",
        candles=[bar.build(index, timeframe) for index, bar in enumerate(bars)],
        fetched_at=datetime.now(tz=timezone.utc),
    )


def with_calm(*pattern_bars: BarSpec, calm: int = 70, **kwargs) -> CandleSeries:
    """A calm backdrop followed by the bars under test (pattern = last bars)."""
    return series(calm_bars(calm, **kwargs) + list(pattern_bars))


# ------------------------------------------------------------------ candlesticks
def bullish_engulfing(*, previous_body: float = 6.0, current_body: float = 8.0, current_open: float = -7.0) -> CandleSeries:
    """Previous bar bearish (0 -> -6 pips), current bar bullish and engulfing.

    With the defaults: current body = [-7, +1] pips, previous body = [-6, 0] pips,
    so the coverage of the previous body is 100% and the current body is x1.33.
    """
    previous = BarSpec(open=0.0, high=1.0, low=-7.0, close=-previous_body)
    current_close = current_open + current_body
    current = BarSpec(
        open=current_open,
        high=max(current_open, current_close) + 0.2,
        low=min(current_open, current_close) - 0.2,
        close=current_close,
    )
    return with_calm(previous, current)


def bearish_engulfing(*, previous_body: float = 6.0, current_body: float = 8.0) -> CandleSeries:
    previous = BarSpec(open=0.0, high=7.0, low=-1.0, close=previous_body)
    current_close = 7.0 - current_body
    current = BarSpec(open=7.0, high=7.2, low=current_close - 0.2, close=current_close)
    return with_calm(previous, current)


def bullish_pin_bar(*, body: float = 2.0, lower_wick: float = 12.0, upper_wick: float = 1.0) -> CandleSeries:
    """Small body at the top of the range, long lower wick: the textbook pin bar."""
    low = 0.0
    open_ = low + lower_wick
    close = open_ + body
    return with_calm(BarSpec(open=open_, high=close + upper_wick, low=low, close=close))


def bearish_pin_bar(*, body: float = 2.0, upper_wick: float = 12.0, lower_wick: float = 1.0) -> CandleSeries:
    high = 14.0
    open_ = high - upper_wick
    close = open_ - body
    return with_calm(BarSpec(open=open_, high=high, low=close - lower_wick, close=close))


def hammer(*, prior_decline: bool = True, bars: int = 8, step: float = 1.5) -> CandleSeries:
    """Bullish pin bar, optionally after a measurable decline (hammer vs pin bar)."""
    pattern = BarSpec(open=12.0, high=15.0, low=0.0, close=14.0)  # body 2, lower wick 12
    prior: list[BarSpec] = []
    if prior_decline:
        price = 12.0
        for _ in range(bars):
            prior.append(BarSpec(open=price, high=price + 0.4, low=price - step - 0.4, close=price - step))
            price -= step
    return with_calm(*prior, pattern, calm=70)


def shooting_star(*, prior_advance: bool = True, bars: int = 8, step: float = 1.5) -> CandleSeries:
    pattern = BarSpec(open=2.0, high=14.0, low=-1.0, close=0.0)  # body 2, upper wick 12
    prior: list[BarSpec] = []
    if prior_advance:
        price = 0.0
        for _ in range(bars):
            prior.append(BarSpec(open=price, high=price + step + 0.4, low=price - 0.4, close=price + step))
            price += step
    return with_calm(*prior, pattern, calm=70)


def inside_bar(*, mother_range: float = 14.0, inside_range: float = 7.0, breach: float = 0.0) -> CandleSeries:
    """Mother bar then a contained bar; ``breach`` pushes both sides out by that many pips."""
    mother = BarSpec(open=0.0, high=mother_range, low=0.0, close=mother_range * 0.6)
    low = 1.0 - breach
    high = low + inside_range
    inside = BarSpec(open=low + 1.0, high=high, low=low, close=high - 1.0)
    return with_calm(mother, inside)


def outside_bar(*, previous_range: float = 6.0, breach: float = 2.0, wick: float = 1.0) -> CandleSeries:
    """Previous bar then a bar that exceeds it on **both** sides.

    The outside bar spans ``previous_range + 2 x breach`` pips (its ratio against
    the previous bar is therefore read directly), with a ``wick`` pip shadow on
    each side of a bullish body.
    """
    previous = BarSpec(open=0.0, high=previous_range, low=0.0, close=previous_range - 1.0)
    low = -breach
    high = previous_range + breach
    current = BarSpec(open=low + wick, high=high, low=low, close=high - wick)
    return with_calm(previous, current)


def doji(*, body: float = 0.5, range_pips: float = 10.0, wick_each: float | None = None) -> CandleSeries:
    each = wick_each if wick_each is not None else (range_pips - body) / 2
    bar = BarSpec(open=5.0, high=5.0 + each + body, low=5.0 - each, close=5.0 + body)
    return with_calm(bar)


# --------------------------------------------------------------------- structure
def impulsion(*, bars: int = 6, step: float = 4.0, wick: float = 0.5) -> CandleSeries:
    """A contiguous bullish run: ``bars`` x ``step`` pips, no meaningful pullback."""
    run: list[BarSpec] = []
    price = 0.0
    for _ in range(bars):
        run.append(BarSpec(open=price, high=price + step + wick, low=price - wick, close=price + step))
        price += step
    return with_calm(*run, calm=70)


def consolidation(*, box_bars: int = 12, box_range: float = 4.0, reference_bars: int = 40, reference_range: float = 12.0) -> CandleSeries:
    """Wide reference bars, then a tight box (measurable compression)."""
    reference: list[BarSpec] = []
    price = 0.0
    for step in range(reference_bars):
        open_, close = price, price + reference_range - 1.0
        reference.append(
            BarSpec(
                open=open_,
                high=open_ + reference_range,
                low=open_,
                close=close,
            )
        )
        price = open_ + 0.5  # slow drift, ranges stay wide

    box: list[BarSpec] = []
    price = 0.0
    for step in range(box_bars):
        open_, close = price, price + box_range - 1.0
        box.append(BarSpec(open=open_, high=open_ + box_range, low=open_, close=close))
        price = open_ + 0.5

    return series(calm_bars(30) + reference + box)


def rejection(*, level_pips: float = 0.0, wick_below: float = 1.0, close_above: float = 4.0) -> CandleSeries:
    """A bullish rejection: a wick dips under a real support, the close comes back above it."""
    bar = BarSpec(open=2.0, high=3.0, low=level_pips - wick_below, close=2.0 + close_above)
    return with_calm(bar, calm=70)


def noise_series(*, bars: int = 300, amplitude: float = 3.0, seed: int = 11, drift: float = 0.0) -> CandleSeries:
    """Deterministic structureless random walk - the negative control of §20.

    No trend, no level, no compression: whatever the engine reports here is a
    false positive by construction, and the number is reported, never hidden.
    """
    import math

    def noise(index: int) -> float:
        value = math.sin((index + 1) * 12.9898 + seed * 78.233) * 43758.5453
        return (value - math.floor(value) - 0.5) * 2 * amplitude

    specs: list[BarSpec] = []
    price = 0.0
    for index in range(bars):
        move = noise(index) + drift
        open_, close = price, price + move
        wick = abs(move) * 0.4 + 0.4
        specs.append(
            BarSpec(
                open=open_,
                high=max(open_, close) + wick,
                low=min(open_, close) - wick,
                close=close,
            )
        )
        price = close
    return series(specs)


# ------------------------------------------------------ chartist bridge fixtures
def chartist_level(kind: str, price: float, *, time: int, detection_id: str = "ct_fixture", pattern: str | None = None):
    """A minimal chartist detection carrying one real level.

    Used to test the *reuse* rules: the price-action engine must consume the levels
    and breakouts of Phase 2 instead of recomputing its own.
    """
    from app.schemas.events import (
        DetectionCategory,
        DetectionDirection,
        DetectionSource,
        DetectionStatus,
        DrawingLevel,
        DrawingSpec,
        PatternDetection,
        WatchedLevel,
    )

    return PatternDetection(
        id=detection_id,
        dedup_key=detection_id,
        symbol="EURUSD",
        timeframe=Timeframe("M15"),
        category=DetectionCategory.CHARTISTE,
        pattern=pattern or kind,
        direction=DetectionDirection.NEUTRAL,
        confidence=50.0,
        status=DetectionStatus.DETECTED,
        source_engine=DetectionSource.CHART_PATTERN_ENGINE,
        detected_at_bar_time=time,
        drawing=DrawingSpec(levels=[DrawingLevel(price=px(price), label=kind, kind=kind)]),
        watch_levels=[WatchedLevel(level_type=kind, price=px(price), direction=DetectionDirection.BULLISH)],
    )


def chartist_breakout(
    *,
    level_pips: float,
    breakout_time: int,
    direction: str = "BULLISH",
    breakout_price_pips: float,
    parent_pattern: str = "RECTANGLE",
    detection_id: str = "ct_breakout",
):
    """A chartist detection whose breakout is already confirmed by Phase 2."""
    from app.schemas.events import (
        BreakoutInfo,
        DetectionCategory,
        DetectionDirection,
        DetectionSource,
        DetectionStatus,
        DrawingLevel,
        DrawingSpec,
        PatternDetection,
    )

    return PatternDetection(
        id=detection_id,
        dedup_key=detection_id,
        symbol="EURUSD",
        timeframe=Timeframe("M15"),
        category=DetectionCategory.CHARTISTE,
        pattern=parent_pattern,
        direction=DetectionDirection(direction),
        confidence=60.0,
        status=DetectionStatus.CONFIRMED,
        source_engine=DetectionSource.CHART_PATTERN_ENGINE,
        detected_at_bar_time=breakout_time,
        drawing=DrawingSpec(levels=[DrawingLevel(price=px(level_pips), label="UPPER", kind="LEVEL")]),
        breakout=BreakoutInfo(
            parent_detection_id=detection_id,
            level=px(level_pips),
            level_type="UPPER",
            direction=DetectionDirection(direction),
            breakout_price=px(breakout_price_pips),
            breakout_time=breakout_time,
            confirming_candle_time=breakout_time,
            candles_to_breakout=3,
            buffer_pips=1.0,
            volume=None,
        ),
    )


def bar_time(index: int, timeframe: str = "M15") -> int:
    return START + index * TF_SECONDS[timeframe]
