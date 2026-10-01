"""Synthetic OHLC builders - TEST FIXTURES ONLY.

Nothing here is ever imported by the application: the production code path only
consumes real provider data. These builders make deterministic bar series with
exact, verifiable geometry so each detector can be tested on a known answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.market import Candle, CandleSeries, Timeframe

PIP = 0.0001
DEFAULT_START = 1_760_000_000  # 2025-10-08 18:13:20 UTC (arbitrary fixed anchor)
TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def _noise(index: int, amplitude: float, seed: int) -> float:
    """Deterministic pseudo-noise (no randomness dependency in tests)."""
    if amplitude == 0:
        return 0.0
    value = math.sin((index + 1) * 12.9898 + seed * 78.233) * 43758.5453
    return (value - math.floor(value) - 0.5) * 2 * amplitude


def build_series(
    waypoints: list[float],
    *,
    bars_per_leg: int = 8,
    symbol: str = "EURUSD",
    timeframe: str = "M15",
    digits: int = 5,
    pip: float = PIP,
    wick_pips: float = 0.6,
    noise_pips: float = 0.0,
    seed: int = 7,
    start_time: int = DEFAULT_START,
    closed: bool = True,
    extra_bars: int = 0,
) -> CandleSeries:
    """Linear path through ``waypoints``, one leg every ``bars_per_leg`` bars.

    Waypoint prices are hit exactly (the pivot price is therefore known), while
    intermediate bars carry a small deterministic deviation so the series is not
    a perfectly straight line.
    """
    if len(waypoints) < 2:
        raise ValueError("at least two waypoints are required")
    if bars_per_leg < 3:
        raise ValueError("bars_per_leg must be >= 3 so pivots can be confirmed")

    wick = wick_pips * pip
    amplitude = noise_pips * pip
    prices: list[float] = []
    #: index -> +1 when the bar must spike upward (it is a swing high), -1 for a low
    spikes: dict[int, int] = {}

    for leg_index in range(len(waypoints) - 1):
        start, end = waypoints[leg_index], waypoints[leg_index + 1]
        for step in range(1, bars_per_leg + 1):
            fraction = step / bars_per_leg
            price = start + (end - start) * fraction
            absolute_index = leg_index * bars_per_leg + step - 1
            if step == bars_per_leg:  # the waypoint itself: exact, no noise
                following = (
                    waypoints[leg_index + 2]
                    if leg_index + 2 < len(waypoints)
                    else waypoints[leg_index + 1] - (waypoints[leg_index + 1] - waypoints[leg_index])
                )
                # a reversal bar wicks beyond its close, which is what makes the
                # pivot strictly dominant (and matches how real swings print)
                spikes[absolute_index] = 1 if end > following else -1
            elif amplitude:
                price += _noise(absolute_index, amplitude, seed)
            prices.append(price)

    if extra_bars:
        last = prices[-1]
        for step in range(1, extra_bars + 1):
            prices.append(last + _noise(len(prices) + step, amplitude, seed))

    candles: list[Candle] = []
    previous_close = prices[0]
    for index, close in enumerate(prices):
        open_ = previous_close
        spike = spikes.get(index, 0)
        high = max(open_, close) + (wick * 2.0 if spike > 0 else wick * 0.4)
        low = min(open_, close) - (wick * 2.0 if spike < 0 else wick * 0.4)
        candles.append(
            Candle(
                time=start_time + index * TF_SECONDS[timeframe],
                open=round(open_, digits),
                high=round(high, digits),
                low=round(low, digits),
                close=round(close, digits),
                volume=None,  # the real Forex provider returns no volume: never invent it
                closed=closed,
            )
        )
        previous_close = close

    return CandleSeries(
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        provider="fixture",
        candles=candles,
        fetched_at=datetime.now(tz=timezone.utc),
    )


# ------------------------------------------------------------------ geometry
BPL = 14  # bars per leg (keeps pivots well separated and series >= 80 bars)


@dataclass
class Scenario:
    """A named fixture: series + the answer the detector must find."""

    series: CandleSeries
    expected_pattern: str | None
    expected_direction: str | None = None
    description: str = ""


def double_top(
    breakout: bool = False,
    tolerance_pips: float = 0.5,
    depth_pips: float = 25,
    retest: bool = False,
    invalidation: bool = False,
    expiring: bool = False,
) -> Scenario:
    """Two peaks 0.5 pip apart, 25-pip valley, optional breakout / retest / failure."""
    peak = 1.1100
    valley = peak - depth_pips / 10000
    waypoints = [
        1.0960, 1.1000, 1.1040,          # lead-in
        peak,                            # peak 1
        valley,                          # valley (neckline)
        peak - tolerance_pips / 10000,   # peak 2
        1.1085,                          # drift away (no breakout)
    ]
    if breakout or retest:
        waypoints += [valley - 0.0030]  # a real bearish break of the neckline
    if retest:
        # the broken neckline is revisited from below, then price resumes down
        waypoints += [valley - 0.0001, valley - 0.0035]
    if invalidation:
        # a close back above both peaks invalidates the formation; the neckline is
        # never broken first (otherwise the pattern would simply be confirmed)
        waypoints += [peak + 0.0030]
    if expiring:
        # nothing happens for far longer than max_bars_to_confirm
        waypoints += [1.1085, 1.1090, 1.1085, 1.1088, 1.1086]
    description = f"double top {tolerance_pips} pip apart, valley {depth_pips} pips"
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="DOUBLE_TOP",
        expected_direction="BEARISH",
        description=f"{description}, breakout={breakout}, retest={retest}, invalidation={invalidation}",
    )


def double_bottom(breakout: bool = False) -> Scenario:
    trough = 1.1000
    summit = trough + 0.0025
    waypoints = [1.1140, 1.1100, 1.1060, trough, summit, trough + 0.00005, 1.1030]
    if breakout:
        waypoints += [summit + 0.0030]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="DOUBLE_BOTTOM",
        expected_direction="BULLISH",
        description=f"double bottom, breakout={breakout}",
    )


def head_shoulders(breakout: bool = False, inverse: bool = False) -> Scenario:
    if not inverse:
        waypoints = [
            1.1040, 1.1000, 1.1045,
            1.1080,   # left shoulder
            1.1032,   # valley 1
            1.1140,   # head
            1.1035,   # valley 2
            1.1082,   # right shoulder
            1.1050,   # drift (neckline ~1.1033 not yet broken)
        ]
        if breakout:
            waypoints += [1.0980]
        pattern, direction = "HEAD_SHOULDERS", "BEARISH"
    else:
        waypoints = [
            1.0960, 1.1000, 1.0955,
            1.0920,   # left shoulder
            1.0968,   # peak 1
            1.0860,   # head (lower low)
            1.0965,   # peak 2
            1.0918,   # right shoulder
            1.0950,
        ]
        if breakout:
            waypoints += [1.1020]
        pattern, direction = "INVERSE_HEAD_SHOULDERS", "BULLISH"
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern=pattern,
        expected_direction=direction,
        description=f"{pattern} breakout={breakout}",
    )


def ascending_triangle(breakout: bool = False) -> Scenario:
    """Flat resistance touched 3 times, rising support touched 3 times."""
    resistance = 1.1100
    waypoints = [
        1.1040, 1.1000,                  # lead-in into the first support
        resistance,                      # touch 1
        1.1030,                          # support 2
        resistance,                      # touch 2
        1.1060,                          # support 3
        resistance,                      # touch 3
        1.1090,                          # drift inside the triangle
    ]
    if breakout:
        waypoints += [1.1140]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="ASCENDING_TRIANGLE",
        expected_direction="BULLISH",
        description=f"ascending triangle, breakout={breakout}",
    )


def descending_triangle(breakout: bool = False) -> Scenario:
    """Flat support touched 3 times, descending resistance touched 3 times."""
    support = 1.0900
    waypoints = [
        1.0960, 1.1000,
        support,
        1.0970,
        support,
        1.0940,
        support,
        1.0910,
    ]
    if breakout:
        waypoints += [1.0860]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="DESCENDING_TRIANGLE",
        expected_direction="BEARISH",
        description=f"descending triangle, breakout={breakout}",
    )


def symmetrical_triangle(breakout: bool = False) -> Scenario:
    """Lower highs and higher lows, evenly spaced so both lines are exact."""
    waypoints = [
        1.1060, 1.1100, 1.0980,   # high 1 / low 1
        1.1080,                   # lower high 2 (-2 pips)
        1.1000,                   # higher low 2 (+2 pips)
        1.1060,                   # lower high 3 (-2 pips)
        1.1020,                   # higher low 3 (+2 pips)
        1.1030,                   # small bounce inside
    ]
    if breakout:
        waypoints += [1.1075]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=10, symbol="EURUSD"),
        expected_pattern="SYMMETRICAL_TRIANGLE",
        expected_direction="NEUTRAL",
        description=f"symmetrical triangle, breakout={breakout}",
    )


def rising_wedge(breakout: bool = False) -> Scenario:
    """Both boundaries rise, the lows rise faster -> convergence (bearish)."""
    waypoints = [
        1.1180, 1.1200,   # lead-in, high 1
        1.1000,           # low 1
        1.1208,           # high 2
        1.1053,           # low 2
        1.1216,           # high 3
        1.1106,           # low 3
        1.1150,           # drift inside the wedge
    ]
    if breakout:
        waypoints += [1.1050]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="RISING_WEDGE",
        expected_direction="BEARISH",
        description=f"rising wedge, breakout={breakout}",
    )


def falling_wedge(breakout: bool = False) -> Scenario:
    """Mirror of the rising wedge: both boundaries fall and converge (bullish)."""
    waypoints = [
        1.1120, 1.1100,
        1.1300,
        1.1092,
        1.1247,
        1.1084,
        1.1194,
        1.1150,
    ]
    if breakout:
        waypoints += [1.1250]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="FALLING_WEDGE",
        expected_direction="BULLISH",
        description=f"falling wedge, breakout={breakout}",
    )


def rectangle(breakout: bool = False) -> Scenario:
    resistance, support = 1.1050, 1.1000
    waypoints = [
        1.1025, resistance, support, resistance, support, resistance, support, 1.1020,
    ]
    if breakout:
        waypoints += [1.1090]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="RECTANGLE",
        expected_direction="NEUTRAL",
        description=f"rectangle {resistance}/{support}, breakout={breakout}",
    )


def bull_flag(breakout: bool = False, kind: str = "FLAG") -> Scenario:
    """A down leg into a swing low, an 80-pip impulse, then a tight box.

    FLAG: the box boundaries are parallel (both drifting gently down).
    PENNANT: the highs descend while the lows ascend (real contraction).
    """
    waypoints = [1.1000, 1.0980, 1.1060]  # low at bar 9, pole top at bar 19
    if kind == "FLAG":
        # parallel boundaries, both drifting gently down (equal slopes)
        waypoints += [1.1050, 1.1053, 1.1049, 1.1052, 1.1051]
    else:
        # converging boundaries: highs descend while lows ascend
        waypoints += [1.1046, 1.1054, 1.1048, 1.1052, 1.1050]
    if breakout:
        waypoints += [1.1090]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=10, symbol="EURUSD"),
        expected_pattern=f"BULL_{kind}",
        expected_direction="BULLISH",
        description=f"bull {kind.lower()} (80-pip pole + tight box), breakout={breakout}",
    )


def bear_flag(breakout: bool = False, kind: str = "FLAG") -> Scenario:
    """Mirror of the bull flag: an up leg, a -80-pip impulse, then a box."""
    waypoints = [1.0980, 1.1000, 1.0920]  # high at bar 9, pole bottom at bar 19
    if kind == "FLAG":
        # parallel boundaries, both drifting gently up (equal slopes)
        waypoints += [1.0930, 1.0927, 1.0931, 1.0928, 1.0932, 1.0930]
    else:
        # converging boundaries: lows ascend while highs descend
        waypoints += [1.0934, 1.0926, 1.0932, 1.0928, 1.0930]
    if breakout:
        waypoints += [1.0890]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=10, symbol="EURUSD"),
        expected_pattern=f"BEAR_{kind}",
        expected_direction="BEARISH",
        description=f"bear {kind.lower()} (-80-pip pole + tight box), breakout={breakout}",
    )


def support_resistance() -> Scenario:
    """Three touches of the same resistance and three of the same support."""
    resistance, support = 1.1100, 1.1020
    waypoints = [1.1060, resistance, support, resistance, support, resistance, support, 1.1060]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="RESISTANCE",
        expected_direction="BEARISH",  # a resistance is a bearish barrier
        description="3 touches resistance + 3 touches support",
    )


def channel(breakout: bool = False) -> Scenario:
    """Rising channel: parallel ascending lines, several touches each."""
    waypoints = [
        1.0980, 1.1000, 1.1080, 1.1030, 1.1110, 1.1060, 1.1140, 1.1090, 1.1170,
    ]
    if breakout:
        waypoints += [1.1160]
    return Scenario(
        series=build_series(waypoints, bars_per_leg=BPL, symbol="EURUSD"),
        expected_pattern="CHANNEL",
        expected_direction="BULLISH",
        description=f"rising channel, breakout={breakout}",
    )


def flat_noise(bars: int = 120, amplitude_pips: float = 8, seed: int = 3) -> CandleSeries:
    """Compressed pseudo-random walk used as a NEGATIVE control (no clean geometry)."""
    price = 1.1000
    waypoints: list[float] = [price]
    for index in range(bars // 4):
        price += _noise(index, amplitude_pips / 10000, seed)
        waypoints.append(price)
    return build_series(waypoints, bars_per_leg=4, noise_pips=amplitude_pips, seed=seed)


ALL_POSITIVE_SCENARIOS = [
    double_top(),
    double_bottom(),
    head_shoulders(),
    head_shoulders(inverse=True),
    ascending_triangle(),
    descending_triangle(),
    symmetrical_triangle(),
    rising_wedge(),
    falling_wedge(),
    rectangle(),
    bull_flag(),
    bear_flag(),
    bull_flag(kind="PENNANT"),
    bear_flag(kind="PENNANT"),
    support_resistance(),
    channel(),
]
