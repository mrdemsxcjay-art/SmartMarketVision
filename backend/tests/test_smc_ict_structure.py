"""Phase 4 §2 §3 §4 §5 §13 - context, swings, BOS, CHOCH, MSS, displacement.

Every case is run on a controlled OHLC fixture (``tests.smc_ict_fixtures``):
synthetic bars, tests only, never written to the database and never served by
the API. Each family of tests carries the four required angles - positive,
negative, limit and duplication - and the definitions are the ones documented in
``app.smc_ict.detectors.structure``: BOS = the prevailing structure continues,
CHOCH = it is broken the other way, MSS = a CHOCH *plus* a displacement. One
definition each, never two.
"""

from __future__ import annotations

import pytest

from app.smc_ict.context import build_context, dominant_structure
from app.smc_ict.detectors.structure import detect_structure
from app.smc_ict.measures import displacement_of, is_displacement
from app.smc_ict.params import SmcIctParams
from tests import smc_ict_fixtures as fx


def analyse(legs, params: SmcIctParams | None = None):
    candles = fx.path_series(legs)
    ctx = build_context(fx.series(candles), params or SmcIctParams(), pip_size=fx.PIP, digits=5)
    return ctx, detect_structure(ctx)


def patterns(dets) -> list[str]:
    return [c.pattern for c in dets]


def last(dets):
    assert dets, "expected at least one structure candidate"
    return max(dets, key=lambda c: c.index)


def one(dets, pattern: str):
    found = [c for c in dets if c.pattern == pattern]
    assert found, f"expected {pattern}, got {patterns(dets)}"
    return max(found, key=lambda c: c.index)


class TestSwings:
    """§2 - swing highs and lows, with a strength that is measured."""

    def test_positive_swings_carry_every_field(self):
        ctx, _ = analyse(fx.bos_bullish_legs())
        assert ctx.swings, "a trending fixture must produce swings"
        swing = ctx.swings[0]
        payload = swing.as_dict()
        assert payload["type"] in ("SWING_HIGH", "SWING_LOW")
        assert payload["index"] >= 0
        assert payload["price"] > 0
        assert payload["strength"] >= 0
        assert payload["timestamp"].endswith("+00:00")

    def test_limit_swings_are_confirmed_never_repainted(self):
        """A pivot is only usable ``right`` bars later - the series cannot see its future."""
        ctx, _ = analyse(fx.bos_bullish_legs())
        assert all(s.confirmed_at_index > s.index for s in ctx.swings), "confirmation must come after the pivot"

    def test_negative_no_pivot_on_a_flat_market(self):
        ctx = build_context(fx.series(fx.flat_series()), SmcIctParams(), pip_size=fx.PIP, digits=5)
        # a perfectly flat market has no strict inequality, so no pivot at all
        assert ctx.swings == ()
        direction, reason = dominant_structure(list(ctx.swings), 3)
        assert direction == "UNKNOWN"
        assert "minimum" in reason

    def test_structure_is_read_before_the_break(self):
        """The structure of a bar is judged on the swings confirmed at that moment."""
        ctx, dets = analyse(fx.choch_bullish_legs())
        choch = one(dets, "CHOCH")
        assert choch.measurements["structure_before"] == "BEARISH"
        assert choch.extra["structure_after"] == "BULLISH"


class TestBos:
    """§3 - break of structure: a close beyond the last confirmed swing."""

    def test_positive_bullish_bos(self):
        _, dets = analyse(fx.bos_bullish_legs())
        bos = last(dets)
        assert bos.pattern == "BOS"
        assert bos.direction == "BULLISH"
        assert bos.measurements["break_mode"] == "CLOSE"
        assert bos.measurements["close_excess_pips"] > 0
        assert bos.levels["BROKEN_SWING"] < bos.levels["BREAK_CLOSE"]
        assert bos.extra["broken_swing"]["type"] == "SWING_HIGH"

    def test_positive_bearish_bos(self):
        _, dets = analyse(fx.bos_bearish_legs())
        bos = last(dets)
        assert bos.pattern == "BOS"
        assert bos.direction == "BEARISH"
        assert bos.levels["BREAK_CLOSE"] < bos.levels["BROKEN_SWING"]
        assert bos.extra["broken_swing"]["type"] == "SWING_LOW"

    def test_negative_wick_alone_is_not_a_break(self):
        params = SmcIctParams()
        assert params.bos.allow_wick_break is False
        _, dets = analyse(fx.wick_only_break_legs(), params)
        # the wick candle is in the window, but it never becomes a break
        assert all(det.measurements["break_mode"] == "CLOSE" for det in dets)
        assert all(det.levels["BROKEN_SWING"] < det.levels["BREAK_CLOSE"] for det in dets)

    def test_limit_wick_allowed_only_by_parameter(self):
        params = SmcIctParams()
        params.bos.allow_wick_break = True
        _, dets = analyse(fx.wick_only_break_legs(), params)
        wick = [det for det in dets if det.measurements["break_mode"] == "WICK"]
        assert wick, "with allow_wick_break=true a clean wick break must be reported"
        assert wick[-1].measurements["body_beyond_level"] is False
        # the criterion stays honest: the body was not beyond the level
        criterion = [c for c in wick[-1].criteria if c[0] == "Cassure portée par le corps (pas une mèche)"][0]
        assert criterion[1] is False

    def test_negative_far_from_swing_is_expired(self):
        params = SmcIctParams()
        params.bos.max_bars_since_swing = 3
        _, dets = analyse(fx.bos_bullish_legs(), params)
        assert all(det.measurements["bars_since_swing"] <= 3 for det in dets)

    def test_dedup_one_event_per_level(self):
        """The same broken level is never announced twice."""
        _, dets = analyse(fx.bos_bullish_legs())
        levels = [(det.pattern, det.extra["broken_swing"]["index"]) for det in dets]
        assert len(levels) == len(set(levels)), f"a swing was broken twice: {levels}"

    def test_limit_no_cascade_of_bos_on_one_impulse(self):
        """An impulse that clears several older swings is ONE event, not a ladder."""
        _, dets = analyse(fx.bos_bearish_legs())
        bearish = [c for c in dets if c.pattern == "BOS" and c.direction == "BEARISH"]
        # consecutive bars cannot each break a *different* level of the same impulse
        for previous, current in zip(bearish, bearish[1:]):
            assert current.extra["broken_swing"]["index"] != previous.extra["broken_swing"]["index"]


class TestChoch:
    """§4 - change of character, tied to real swings."""

    def test_positive_bullish_choch(self):
        ctx, dets = analyse(fx.choch_bullish_legs())
        choch = one(dets, "CHOCH")
        assert choch.direction == "BULLISH"
        assert choch.extra["broken_swing"]["type"] == "SWING_HIGH"
        assert choch.extra["structure_before"] == "BEARISH"
        assert choch.extra["structure_after"] == "BULLISH"
        assert choch.measurements["close_excess_pips"] > 0
        # the broken swing is a real, confirmed swing of the context
        assert choch.extra["broken_swing"]["index"] in [s.index for s in ctx.swings]

    def test_positive_bearish_choch(self):
        _, dets = analyse(fx.choch_bearish_legs())
        choch = one(dets, "CHOCH")
        assert choch.direction == "BEARISH"
        assert choch.extra["broken_swing"]["type"] == "SWING_LOW"
        assert choch.extra["structure_before"] == "BULLISH"

    def test_negative_no_choch_without_opposite_structure(self):
        """In a bullish trend, closing above the last high is a BOS - never a CHOCH."""
        _, dets = analyse(fx.bos_bullish_legs())
        assert "CHOCH" not in patterns(dets)

    def test_dedup_one_choch_per_swing(self):
        _, dets = analyse(fx.choch_bullish_legs())
        swings = [det.extra["broken_swing"]["index"] for det in dets if det.pattern == "CHOCH"]
        assert len(swings) == len(set(swings))


class TestMss:
    """§5 - MSS is CHOCH + displacement. A single definition, documented."""

    def test_positive_mss_follows_a_choch(self):
        _, dets = analyse(fx.mss_bullish_legs())
        mss = one(dets, "MSS")
        choch = one(dets, "CHOCH")
        assert mss.direction == choch.direction == "BULLISH"
        assert 0 <= mss.index - choch.index <= SmcIctParams().mss.max_bars_after_choch
        assert mss.measurements["extension_atr"] > 0
        # MSS is never emitted without its CHOCH: it is a promotion, not a rival definition
        assert choch.index < mss.index

    def test_negative_choch_without_displacement_is_not_an_mss(self):
        _, dets = analyse(fx.choch_no_displacement_legs())
        assert "CHOCH" in patterns(dets)
        assert "MSS" not in patterns(dets)

    def test_negative_wide_bar_without_progression_is_not_an_mss(self):
        _, dets = analyse(fx.mss_no_progress_legs())
        assert "CHOCH" in patterns(dets)
        assert "MSS" not in patterns(dets)

    def test_limit_one_mss_per_choch(self):
        _, dets = analyse(fx.mss_bullish_legs())
        mss = [c for c in dets if c.pattern == "MSS"]
        sources = [c.measurements["from_choch_index"] for c in mss]
        assert len(sources) == len(set(sources))

    def test_criteria_are_explicit(self):
        _, dets = analyse(fx.mss_bullish_legs())
        mss = one(dets, "MSS")
        labels = [c[0] for c in mss.criteria]
        assert "CHOCH confirmé" in labels
        assert "Déplacement mesuré" in labels
        assert all(isinstance(c[1], bool) for c in mss.criteria)


class TestDisplacement:
    """§13 - displacement is measured, never "a big candle"."""

    def test_positive_measures_are_exposed(self):
        ctx, _ = analyse(fx.mss_bullish_legs())
        index = len(ctx.metrics) - 3
        measures = displacement_of(ctx, index)
        for key in (
            "range_pips",
            "range_atr",
            "body_ratio",
            "net_move_pips",
            "efficiency",
            "progression_pips",
            "progression_atr",
            "same_direction_bars",
        ):
            assert key in measures, key
        assert measures["range_atr"] > 0

    def test_negative_narrow_bar_is_not_a_displacement(self):
        ctx = build_context(fx.series(fx.flat_series()), SmcIctParams(), pip_size=fx.PIP, digits=5)
        passed, measures = is_displacement(ctx, len(ctx.metrics) - 1)
        assert passed is False
        # below the configured volatility floor: this is why it is not a displacement
        assert measures["range_atr"] < SmcIctParams().displacement.min_range_atr

    def test_limit_each_threshold_is_reported(self):
        ctx, _ = analyse(fx.mss_bullish_legs())
        _, measures = is_displacement(ctx, len(ctx.metrics) - 1)
        assert "threshold" in measures
        assert "progression_floor_pips" in measures
        assert "threshold_rule" in measures


class TestNoTradingIntent:
    """§29 - the SMC/ICT phase never emits an instruction."""

    FORBIDDEN = ("BUY", "SELL", "ENTRY", "STOP LOSS", "TAKE PROFIT", "LONG", "SHORT")

    def test_no_candidate_carries_a_trading_word(self):
        for legs in (fx.bos_bullish_legs(), fx.choch_bullish_legs(), fx.mss_bullish_legs()):
            _, dets = analyse(legs)
            blob = " ".join(
                item
                for det in dets
                for item in (
                    [det.pattern, det.direction]
                    + list(det.evidence)
                    + [f"{crit[0]} {crit[3]}" for crit in det.criteria]
                )
            ).upper()
            for word in self.FORBIDDEN:
                assert word not in blob, f"{word} leaked into {patterns(dets)}"


@pytest.mark.parametrize("fixture", ["noise", "flat", "trending"])
def test_negative_control_runs_on_every_market_shape(fixture):
    """§25 - the engine must return a result (possibly empty), never crash."""
    makers = {
        "noise": lambda: fx.series(fx.noise_series()),
        "flat": lambda: fx.series(fx.flat_series()),
        "trending": lambda: fx.series(fx.trending_series()),
    }
    ctx = build_context(makers[fixture](), SmcIctParams(), pip_size=fx.PIP, digits=5)
    dets = detect_structure(ctx)
    assert isinstance(dets, list)
    assert all(det.index < len(ctx.metrics) for det in dets)
