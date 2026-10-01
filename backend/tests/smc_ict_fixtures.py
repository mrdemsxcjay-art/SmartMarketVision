"""Controlled OHLC fixtures for the SMC/ICT tests (Phase 4 §24).

Everything here is SYNTHETIC and exists for the tests only. It is never written
to the database and never served by the API: the price-action and SMC engines
read their data from the real provider.

The generator builds a *price path*: a list of legs ``(delta_pips, bars)``. Each
leg moves linearly; the LAST bar of a leg carries a small spike, which is what
makes a pivot real (Phase 1/2 pivots need the extreme to be strictly greater than
its neighbours - two equal highs produce no pivot, exactly like on a real
market). Turning points are therefore genuine swing points, and every fixture
below can be read as a small, fully known market.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.market import Candle, CandleSeries, DataState, Timeframe

PIP = 0.0001
BASE = 1.10000
START = 1760000000
TF_SECONDS = 900  # M15

#: small wick carried by every ordinary bar
WICK = 0.5 * PIP
#: spike carried by the last bar of a leg, so the turning point is a real pivot
SPIKE = 3.0 * PIP


def px(pips: float) -> float:
    """Convert pips into a price distance from the base."""
    return BASE + pips * PIP


def bar(index: int, open_: float, high: float, low: float, close: float, volume: float | None = None) -> Candle:
    return Candle(
        time=START + index * TF_SECONDS,
        open=round(open_, 8),
        high=round(high, 8),
        low=round(low, 8),
        close=round(close, 8),
        volume=volume,
    )


#: neutral oscillation prepended to every scenario so the fixtures are real
#: markets (>= the engine's minimum bar count) and so the scenario swings are
#: never the very first bars of the series. The two extremes are equal, so the
#: warm-up itself breaks no structure: it is a range, not a trend.
WARMUP: list[tuple[float, int]] = [(+30.0, 4), (-30.0, 4)] * 3


def path_series(
    legs: list,
    start_pips: float = 0.0,
    symbol: str = "EURUSD",
    wick: float = WICK,
    spike: float = SPIKE,
    warmup: bool = True,
) -> list[Candle]:
    """Build real-looking bars along a path of ``(delta_pips, bars)`` legs.

    A leg may carry a third element, a dict of options applied to its LAST bar:
    ``jump`` (pips added to that bar's open - creates a gap), ``wick_high`` /
    ``wick_low`` (override the ordinary wick on that side, in pips) and
    ``spike`` (override the turning spike). This is what makes the fine cases
    (a wick that pierces a level without closing beyond it, an FVG, a sweep)
    expressible with real-looking candles instead of hand-made ones.
    """
    legs = [(leg[0], leg[1], (leg[2] if len(leg) > 2 else {})) for leg in legs]
    if warmup:
        # a warm-up pair repeated until the market is at least 70 bars long, so
        # every scenario is scanned on a real market and not on a stub
        extra: list = [(d, b, {}) for d, b in WARMUP]
        while sum(b for _, b, _ in extra) + sum(b for _, b, _ in legs) < 70:
            extra = extra + [(d, b, {}) for d, b in WARMUP]
        legs = extra + legs
    candles: list[Candle] = []
    price = px(start_pips)
    index = 0
    for delta_pips, bars, opts in legs:
        assert bars >= 1
        step = (delta_pips * PIP) / bars
        up = delta_pips >= 0
        jump = opts.get("jump", 0.0) * PIP
        for k in range(bars):
            open_ = price + (jump if k == bars - 1 else 0.0)
            close = open_ + step
            low = min(open_, close) - opts.get("wick_low", wick / PIP) * PIP
            high = max(open_, close) + opts.get("wick_high", wick / PIP) * PIP
            if k == bars - 1:
                # turning bar: the spike makes this extreme strictly unique
                turning = opts.get("spike", spike / PIP) * PIP
                if up:
                    high = max(open_, close) + turning
                else:
                    low = min(open_, close) - turning
            candles.append(bar(index, open_, high, low, close))
            price = close
            index += 1
    return candles


def series(candles: list[Candle], symbol: str = "EURUSD", timeframe: Timeframe = Timeframe.M15) -> CandleSeries:
    return CandleSeries(
        symbol=symbol,
        timeframe=timeframe,
        provider="fixture",
        data_state=DataState.CONNECTED,
        fetched_at=datetime.now(tz=timezone.utc),
        candles=candles,
    )


# --------------------------------------------------------------- scenarios
def bos_bullish_legs() -> list[tuple[float, int]]:
    """Uptrend that keeps making higher lows, then breaks its own last high.

    Structure is already BULLISH when the break happens, so the event is a
    continuation BOS - not a character change.
    """
    return [
        (+20.0, 4),
        (-14.0, 4),     # swing low, inside the warm-up range
        (+40.0, 6),     # higher high
        (-16.0, 4),     # higher low -> bullish structure
        (+34.0, 5),     # higher high again
        (-15.0, 4),     # higher low
        (+30.0, 5),     # closes above the last swing high -> BOS bullish
    ]


def bos_bearish_legs() -> list[tuple[float, int]]:
    """Mirror image of :func:`bos_bullish_legs` (downtrend continuation)."""
    return [
        (-20.0, 4),
        (+14.0, 4),
        (-40.0, 6),
        (+16.0, 4),
        (-34.0, 5),
        (+15.0, 4),
        (-30.0, 5),     # closes below the last swing low -> BOS bearish
    ]


def wick_only_break_legs() -> list[tuple[float, int, dict]]:
    """A candle whose wick pierces the last swing high but closes below it.

    No BOS without ``bos.allow_wick_break``: this is the negative case for the
    "a wick alone is not a break" rule.
    """
    return [
        (+20.0, 4),
        (-14.0, 4),                 # swing low
        (+40.0, 6),                 # higher high (the level that will be tested)
        (-16.0, 4),                 # higher low
        (+20.0, 4),
        (-6.0, 2, {"wick_high": 26.0}),   # wick well above the high, close below
    ]


def choch_bullish_legs() -> list[tuple[float, int]]:
    """Bearish structure, then a close above the last swing high."""
    return [
        (-30.0, 5),     # lower low
        (+14.0, 4),     # swing high
        (-36.0, 6),     # lower low -> bearish structure
        (+12.0, 4),     # lower high
        (-24.0, 5),     # lower low
        (+60.0, 6),     # reversal: closes far above the last swing high -> CHOCH
    ]


def choch_bearish_legs() -> list[tuple[float, int]]:
    """Mirror image of :func:`choch_bullish_legs`."""
    return [
        (+30.0, 5),
        (-14.0, 4),
        (+36.0, 6),
        (-12.0, 4),
        (+24.0, 5),
        (-60.0, 6),
    ]


def mss_bullish_legs() -> list[tuple[float, int]]:
    """CHOCH whose reversal leg is a single wide displacement candle."""
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+60.0, 2),     # two wide bars: the reversal bar is a displacement
    ]


def choch_no_displacement_legs() -> list[tuple[float, int]]:
    """A reversal that changes character, but with no displacement candle.

    The move happens through many narrow, overlapping bars: the closes still
    clear the swing high, so it is a CHOCH, but no single bar is wide enough to
    qualify as displacement - so it must NOT become an MSS.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+6.0, 2),
        (+4.0, 2),
        (+5.0, 2),
        (+6.0, 2),
        (+6.0, 2),
        (+7.0, 2),
        (+6.0, 2),
        (+6.0, 2),
        (+5.0, 2),
        (+6.0, 2),
        (+5.0, 2),
    ]


def mss_no_progress_legs() -> list[tuple[float, int]]:
    """Wide reversal candle that stops right at the level, then stalls.

    The reversal bar is big enough in range and body terms, but its close only
    just clears the swing high and nothing follows: the progression beyond the
    level stays below the MSS floor, so this is a CHOCH and never an MSS.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+28.5, 2),     # wide bar closing ~1.5 pip above the swing high: CHOCH yes
        (+0.4, 3),      # then it stalls: never 0.8 ATR beyond the level -> no MSS
    ]


def equal_highs_legs(tolerance_pips: float = 1.0) -> list[tuple[float, int]]:
    """Two swing highs at nearly the same price (a liquidity estimate)."""
    return [
        (+35.0, 6),                  # first high around +35 pips
        (-20.0, 5),                  # swing low between the two highs
        (+19.0 + tolerance_pips, 6),  # second high 1 pip below the first: equal
        (-25.0, 6),
        (+10.0, 4),
    ]


def equal_lows_legs(tolerance_pips: float = 1.0) -> list[tuple[float, int]]:
    """Mirror image of :func:`equal_highs_legs`."""
    return [
        (-35.0, 6),
        (+20.0, 5),
        (-19.0 - tolerance_pips, 6),
        (+25.0, 6),
        (-10.0, 4),
    ]


def sweep_bearish_legs(wick_pips: float = 26.0) -> list[tuple[float, int, dict]]:
    """Equal highs, then a candle that pokes above them and closes back below.

    The last candle carries a long upper wick: it pierces the equal-highs level
    and closes well below it - the three-step sweep, in order.
    """
    return [
        (+35.0, 6),                  # first high
        (-20.0, 5),
        (+20.0, 6),                  # second high: equal highs around +35 pips
        (-24.0, 6),
        (+16.0, 4),                  # approach
        (-10.0, 2, {"wick_high": wick_pips}),   # pierce + close back below
    ]


def sweep_bullish_legs(wick_pips: float = 26.0) -> list[tuple[float, int, dict]]:
    """Mirror image: equal lows swept from below, closing back above."""
    return [
        (-35.0, 6),
        (+20.0, 5),
        (-20.0, 6),
        (+24.0, 6),
        (-16.0, 4),
        (+10.0, 2, {"wick_low": wick_pips}),
    ]


def equal_highs_no_sweep_legs() -> list[tuple[float, int]]:
    """Equal highs that are simply broken: a close beyond the level, no re-entry.

    The step-2 rule says this is NOT a sweep, and the detector must stay silent.
    """
    return [
        (+35.0, 6),
        (-20.0, 5),
        (+20.0, 6),
        (-24.0, 6),
        (+34.0, 5),      # closes above the equal highs and stays there
    ]


def fvg_bullish_legs() -> list[tuple]:
    """Three candles leaving a bullish gap (``high[i] < low[i+2]``).

    The middle candle jumps and travels: the band between candle 1's high and
    candle 3's low was never traded, which is exactly what a fair value gap is.
    """
    return [
        (+3.0, 3, {"spike": 0.0}),
        (0.0, 1, {"spike": 0.0}),          # candle 1
        (+12.0, 1, {"jump": 1.0}),         # candle 2: the impulsive middle bar
        (+3.0, 4),                         # candle 3 and after
    ]


def fvg_bearish_legs() -> list[tuple]:
    """Mirror image of :func:`fvg_bullish_legs`."""
    return [
        (-3.0, 3, {"spike": 0.0}),
        (0.0, 1, {"spike": 0.0}),
        (-12.0, 1, {"jump": -1.0}),
        (-3.0, 4),
    ]


def fvg_bullish_active_legs(extra_pips: float = 14.0) -> list[tuple]:
    """A bullish FVG that price never comes back to: it stays ACTIVE."""
    return fvg_bullish_legs() + [(+extra_pips, 4)]


def fvg_bullish_partial_legs() -> list[tuple]:
    """A bullish FVG price dips into, without crossing the whole band."""
    return fvg_bullish_legs() + [(-6.0, 3), (+14.0, 3)]


def fvg_bullish_filled_legs() -> list[tuple]:
    """A bullish FVG price traverses entirely: the band is FILLED."""
    return fvg_bullish_legs() + [(-16.0, 5), (+6.0, 3)]


def order_block_bullish_legs() -> list[tuple]:
    """Last bearish candle, then a displacement that breaks structure upward.

    The block is the origin candle; the trigger is the CHOCH/MSS that follows the
    displacement - exactly the definition the engine implements.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),     # swing high
        (-36.0, 6),     # lower low -> bearish structure
        (+12.0, 4),     # lower high
        (-24.0, 5),     # lower low: the origin candle sits at the end of this leg
        (+60.0, 6),     # displacement + CHOCH bullish
    ]


def order_block_no_break_legs() -> list[tuple]:
    """Same displacement, but the swing high is NOT cleared: no block.

    A zone without a structural break is just a candle.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+18.0, 3),     # displacement, but it stops well below the last swing high
        (-4.0, 3),
    ]


def breaker_bullish_legs() -> list[tuple]:
    """Bullish block, then invalidation, then a structural break the other way.

    ORDER_BLOCK -> INVALIDATION (a close through the zone) -> STRUCTURAL_BREAK
    (bearish here) -> BREAKER. Without the last step the block would simply stay
    invalidated, which is what :func:`breaker_no_promotion_legs` checks.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+60.0, 6),     # CHOCH bullish + displacement -> bullish block
        (-20.0, 4),     # pullback
        (-46.0, 8),     # collapses through the block zone -> INVALIDATION
        (-10.0, 3),     # swing low, confirmed
        (-22.0, 5),     # closes below that swing low -> bearish structural break
    ]


def breaker_no_promotion_legs() -> list[tuple]:
    """Invalidated block with NO structural break after the invalidation.

    The bearish break happens *while* price is still above the zone, then price
    drifts monotonically through the zone (no spike, so no new pivot): the block
    is INVALIDATED, no structural break follows, and the promotion to BREAKER
    must be refused.
    """
    return [
        (-30.0, 5),
        (+14.0, 4),
        (-36.0, 6),
        (+12.0, 4),
        (-24.0, 5),
        (+60.0, 6),                            # bullish block around -64 pips
        (-25.0, 3, {"spike": 0.0}),
        (+8.0, 2, {"spike": 0.0}),             # swing low at -29 pips, confirmed
        (-30.0, 3, {"spike": 0.0}),            # closes below it: structural break
        (+6.0, 2, {"spike": 0.0}),
        (-34.0, 14, {"spike": 0.0, "wick_low": 0.2}),  # drift through the zone
    ]


def displacement_legs() -> list[tuple[float, int]]:
    return [
        (+3.0, 6),
        (-2.0, 4),
        (+45.0, 4),      # one-way move
        (-4.0, 4),
    ]


def dealing_range_legs() -> list[tuple[float, int]]:
    """A clean range with a high, a low, and price back inside."""
    return [
        (+60.0, 8),      # range high
        (-80.0, 10),     # range low
        (+45.0, 8),      # back inside, above equilibrium
        (-10.0, 4),
    ]


def noise_series(seed: int = 7, bars: int = 300, amplitude_pips: float = 6.0) -> list[Candle]:
    """Structureless series used by the §25 negative control."""
    import random

    rng = random.Random(seed)
    candles: list[Candle] = []
    price = px(0.0)
    for index in range(bars):
        open_ = price
        close = price + rng.uniform(-amplitude_pips, amplitude_pips) * PIP
        low = min(open_, close) - rng.uniform(0, amplitude_pips / 2) * PIP
        high = max(open_, close) + rng.uniform(0, amplitude_pips / 2) * PIP
        candles.append(bar(index, open_, high, low, close, volume=None))
        price = close
    return candles


def flat_series(bars: int = 200, jitter_pips: float = 0.2) -> list[Candle]:
    """Dead flat market: the engine must claim nothing."""
    import random

    rng = random.Random(11)
    candles: list[Candle] = []
    price = px(0.0)
    for index in range(bars):
        jump = rng.uniform(-jitter_pips, jitter_pips) * PIP
        open_ = price
        close = price + jump
        low = min(open_, close) - jitter_pips * PIP / 2
        high = max(open_, close) + jitter_pips * PIP / 2
        candles.append(bar(index, open_, high, low, close))
        price = close
    return candles


def trending_series(bars: int = 200, slope_pips: float = 1.5) -> list[Candle]:
    """Strongly directional market (up), with small pullbacks."""
    import random

    rng = random.Random(13)
    candles: list[Candle] = []
    price = px(0.0)
    for index in range(bars):
        drift = slope_pips * PIP if (index // 8) % 4 != 3 else -slope_pips * PIP
        open_ = price
        close = price + drift + rng.uniform(-0.3, 0.3) * PIP
        low = min(open_, close) - 1.0 * PIP
        high = max(open_, close) + 1.0 * PIP
        candles.append(bar(index, open_, high, low, close))
        price = close
    return candles
