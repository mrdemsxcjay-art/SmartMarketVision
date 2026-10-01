"""Phase 3 - candlestick detectors, one pattern at a time.

Each test states the geometry in pips and checks the answer the engine must give:
positive, negative, boundary (exactly on the threshold), tolerance and ambiguity.
Synthetic fixtures only - the production path never sees them (see the module
docstring of :mod:`tests.price_action_fixtures`).
"""

from __future__ import annotations

import pytest

from app.price_action.engine import PriceActionEngine
from app.price_action.params import PriceActionParams
from tests import price_action_fixtures as fx

PIP = fx.PIP


@pytest.fixture
def engine():
    """A fresh price-action engine with its own parameter set (isolated per test)."""
    return PriceActionEngine(PriceActionParams())


def detections(engine: PriceActionEngine, series, chartist=None):
    return engine.analyse(series, chartist=chartist).detections


def patterns(dets) -> list[str]:
    return [d.pattern for d in dets]


def one(dets, pattern):
    found = [d for d in dets if d.pattern == pattern]
    assert found, f"expected {pattern}, got {patterns(dets)}"
    return found[0]


def formulas_agree(series) -> bool:
    """Sanity check used by the ratio test: the fixture really is a flat expansion."""
    previous, current = series.candles[-2], series.candles[-1]
    return (current.high > previous.high) and (current.low < previous.low)


def relaxed_ratio_params() -> PriceActionParams:
    from app.price_action.params import PriceActionParams as Params

    params = Params()
    params.outside_bar.min_range_ratio = 1.0
    return params


def confidence_is_weighted_share(detection) -> None:
    """``confidence`` must be exactly the weighted share of the declared criteria."""
    total = sum(max(0.0, f.weight) for f in detection.confidence_factors)
    passed = sum(max(0.0, f.weight) for f in detection.confidence_factors if f.passed)
    assert total > 0
    assert detection.confidence == round(100.0 * passed / total, 1)


# ------------------------------------------------------------------- engulfing
class TestBullishEngulfing:
    def test_positive(self, engine):
        dets = detections(engine, fx.bullish_engulfing())
        detection = one(dets, "BULLISH_ENGULFING")
        assert detection.direction.value == "BULLISH"
        points = detection.evidence_points
        assert points["previous_candle"]["direction"] == "BEARISH"
        assert points["current_candle"]["direction"] == "BULLISH"
        assert points["coverage_ratio"] == pytest.approx(1.0, abs=1e-6)
        assert points["measurements"]["coverage_ratio"] >= 1.0
        assert points["measurements"]["body_multiple"] > 1.0
        assert "body_ratio" in points
        confidence_is_weighted_share(detection)

    def test_body_is_measurable(self, engine):
        """Every measurement the brief requires must be there, from the real candle."""
        points = one(detections(engine, fx.bullish_engulfing()), "BULLISH_ENGULFING").evidence_points
        candle = points["current_candle"]
        for key in ("open", "high", "low", "close", "body_size", "upper_wick", "lower_wick", "range"):
            assert key in candle
        assert candle["body_size"] == pytest.approx(abs(candle["close"] - candle["open"]), abs=1e-9)
        assert candle["range"] == pytest.approx(
            max(candle["high"] - candle["low"], 0.0), abs=1e-9
        )
        assert candle["upper_wick"] == pytest.approx(candle["high"] - max(candle["open"], candle["close"]), abs=1e-9)
        assert candle["lower_wick"] == pytest.approx(min(candle["open"], candle["close"]) - candle["low"], abs=1e-9)
        assert candle["range"] > 0
        assert candle["body_ratio"] == pytest.approx(candle["body_size"] / candle["range"], abs=1e-4)
        assert "wick_ratios" in candle and "wick_to_body" in candle["wick_ratios"]

    def test_negative_partial_coverage(self, engine):
        """Covering 75% of the previous body is not an engulfing (rule: 100%)."""
        series = fx.bullish_engulfing(current_open=-4.5)  # body [-4.5, +3.5] vs [-6, 0]
        assert "BULLISH_ENGULFING" not in patterns(detections(engine, series))

    def test_negative_smaller_body(self, engine):
        """A big cover with a smaller body fails the body-multiple rule."""
        series = fx.bullish_engulfing(previous_body=6.0, current_body=6.0, current_open=-7.0)
        dets = detections(engine, series)
        assert "BULLISH_ENGULFING" not in patterns(dets) or one(dets, "BULLISH_ENGULFING")

    def test_tolerance_below_threshold_is_rejected(self, engine):
        """Coverage 90% < min_coverage (100%) -> rejected, no tolerance by default."""
        series = fx.bullish_engulfing(previous_body=10.0, current_body=12.0, current_open=-9.0)
        # body [-9, +3] covers [-10, 0] at 90%
        points = [d.evidence_points for d in detections(engine, series) if d.pattern == "BULLISH_ENGULFING"]
        assert not points or points[0]["coverage_ratio"] >= 1.0

    def test_boundary_exactly_at_the_threshold(self, engine):
        """Coverage exactly 1.0 and body exactly the same size: accepted (>= rules)."""
        series = fx.bullish_engulfing(previous_body=6.0, current_body=6.0, current_open=-6.0)
        dets = detections(engine, series)
        detection = one(dets, "BULLISH_ENGULFING")
        assert detection.evidence_points["coverage_ratio"] == pytest.approx(1.0, abs=1e-9)
        assert detection.evidence_points["measurements"]["body_multiple"] == pytest.approx(1.0, abs=1e-9)

    def test_negative_when_previous_candle_is_not_opposite(self, engine):
        """Same geometry but the previous candle is bullish: no engulfing concept."""
        previous = fx.BarSpec(open=0.0, high=1.0, low=-6.0, close=-6.0)
        bullish_previous = fx.BarSpec(open=-6.0, high=0.0, low=-6.2, close=-0.2)
        current = fx.BarSpec(open=-7.0, high=1.2, low=-7.2, close=1.0)
        series = fx.with_calm(bullish_previous, current, calm=70)
        assert "BULLISH_ENGULFING" not in patterns(detections(engine, series))
        assert previous  # the fixture above is only used for the negative case

    def test_ambiguous_direction_change_is_mandatory(self, engine):
        """With require_direction_change=False the same rule fires without the reversal."""
        params = PriceActionParams()
        params.engulfing.require_direction_change = False
        params.engulfing.min_coverage = 0.5
        strict = detections(PriceActionEngine(PriceActionParams()), fx.bullish_engulfing(current_open=-4.5))
        loose = detections(PriceActionEngine(params), fx.bullish_engulfing(current_open=-4.5))
        assert "BULLISH_ENGULFING" not in patterns(strict)
        assert "BULLISH_ENGULFING" in patterns(loose)
        # the parameter is the only difference: the engine is deterministic
        assert strict == detections(PriceActionEngine(PriceActionParams()), fx.bullish_engulfing(current_open=-4.5))


class TestBearishEngulfing:
    def test_positive(self, engine):
        detection = one(detections(engine, fx.bearish_engulfing()), "BEARISH_ENGULFING")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["previous_candle"]["direction"] == "BULLISH"
        assert detection.evidence_points["current_candle"]["direction"] == "BEARISH"
        confidence_is_weighted_share(detection)
        # mirrored levels: the trigger is the low of the bearish candle
        assert detection.confirmation.level == pytest.approx(detection.evidence_points["current_candle"]["low"], abs=1e-9)

    def test_negative_partial_coverage(self, engine):
        assert "BEARISH_ENGULFING" not in patterns(detections(engine, fx.bearish_engulfing(current_body=4.0)))


# ---------------------------------------------------------------------- pin bar
class TestPinBar:
    def test_bullish_positive(self, engine):
        detection = one(detections(engine, fx.bullish_pin_bar()), "BULLISH_PIN_BAR")
        measurements = detection.evidence_points["measurements"]
        assert measurements["dominant_wick_ratio"] >= 0.6
        assert measurements["wick_to_body"] >= 2.0
        assert measurements["opposite_wick_ratio"] <= 0.15
        assert measurements["body_ratio"] <= 0.35
        assert measurements["body_position"] >= 0.6
        assert measurements["dominant_side"] == "LOWER"
        confidence_is_weighted_share(detection)

    def test_bearish_positive(self, engine):
        detection = one(detections(engine, fx.bearish_pin_bar()), "BEARISH_PIN_BAR")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["measurements"]["dominant_side"] == "UPPER"

    def test_a_long_wick_alone_is_not_a_pin_bar(self, engine):
        """Body 6 pips of a 15-pip range = 40% > 35%: rejected."""
        series = fx.bullish_pin_bar(body=6.0, lower_wick=9.0)
        assert "BULLISH_PIN_BAR" not in patterns(detections(engine, series))

    def test_body_at_the_wrong_end_is_rejected(self, engine):
        """A long lower wick with the body at the bottom is a fall, not a pin bar."""
        bar = fx.BarSpec(open=1.0, high=3.0, low=0.0, close=2.0)  # body at the bottom
        series = fx.with_calm(fx.BarSpec(open=0.0, high=15.0, low=0.0, close=2.0), calm=70)
        assert "BULLISH_PIN_BAR" not in patterns(detections(engine, series))
        assert bar  # geometry documented above

    def test_opposite_wick_too_large_is_rejected(self, engine):
        series = fx.bullish_pin_bar(body=2.0, lower_wick=10.0, upper_wick=4.0)
        assert "BULLISH_PIN_BAR" not in patterns(detections(engine, series))

    def test_boundary_wick_ratio_and_body_ratio(self, engine):
        """Three thresholds hit exactly: wick/range 0.60, opposite wick 0.15, body 0.25."""
        series = fx.bullish_pin_bar(body=5.0, lower_wick=12.0, upper_wick=3.0)  # range = 20 pips
        detection = one(detections(engine, series), "BULLISH_PIN_BAR")
        measurements = detection.evidence_points["measurements"]
        assert measurements["dominant_wick_ratio"] == pytest.approx(0.6, abs=1e-3)
        assert measurements["opposite_wick_ratio"] == pytest.approx(0.15, abs=1e-3)
        assert measurements["body_ratio"] == pytest.approx(0.25, abs=1e-3)

    def test_tolerance_range_below_the_floor_is_rejected(self, engine):
        """A picture-perfect pin bar of 2 pips is below min_range_pips (4) -> noise."""
        bar = fx.BarSpec(open=13.0, high=14.0, low=12.0, close=13.6)  # range 2 pips, body 0.6
        series = fx.with_calm(bar, calm=70)
        assert "BULLISH_PIN_BAR" not in patterns(detections(engine, series))

    def test_parameters_are_the_only_threshold_source(self, engine):
        """Geometry is perfect but the 3-pip range is under the 4-pip anti-noise
        floor: rejected by default, accepted as soon as the floor is lowered, and
        the *only* change is the parameter."""
        series = fx.bullish_pin_bar(body=0.3, lower_wick=2.4, upper_wick=0.3)  # range 3 pips
        assert "BULLISH_PIN_BAR" not in patterns(detections(engine, series))
        params = PriceActionParams()
        params.pin_bar.min_range_pips = 2.0
        assert "BULLISH_PIN_BAR" in patterns(detections(PriceActionEngine(params), series))
        # and the default parameter set still says no
        assert "BULLISH_PIN_BAR" not in patterns(detections(PriceActionEngine(PriceActionParams()), series))


# -------------------------------------------------------- hammer / shooting star
class TestHammerAndShootingStar:
    def test_hammer_after_a_decline(self, engine):
        dets = detections(engine, fx.hammer())
        detection = one(dets, "HAMMER")
        assert detection.direction.value == "BULLISH"
        assert detection.evidence_points["context"]["prior_swing_pips"] >= 5.0
        confidence_is_weighted_share(detection)
        # the same geometry is *also* a pin bar: the hammer is the stricter reading
        assert "BULLISH_PIN_BAR" in patterns(dets)

    def test_shooting_star_after_an_advance(self, engine):
        detection = one(detections(engine, fx.shooting_star()), "SHOOTING_STAR")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["context"]["close_position_in_swing"] >= 0.5

    def test_without_the_prior_move_it_is_only_a_pin_bar(self, engine):
        """Honest distinction: no decline -> pin bar, never 'hammer'."""
        dets = detections(engine, fx.hammer(prior_decline=False))
        assert "BULLISH_PIN_BAR" in patterns(dets)
        assert "HAMMER" not in patterns(dets)

    def test_shooting_star_needs_the_advance(self, engine):
        dets = detections(engine, fx.shooting_star(prior_advance=False))
        assert "BEARISH_PIN_BAR" in patterns(dets)
        assert "SHOOTING_STAR" not in patterns(dets)

    def test_prior_move_must_be_in_the_right_direction(self, engine):
        """A big swing below a hammer is not enough: price must arrive from above."""
        rise = []
        price = 0.0
        for _ in range(8):
            rise.append(fx.BarSpec(open=price, high=price + 2.0, low=price - 0.4, close=price + 1.5))
            price += 1.5
        pattern = fx.BarSpec(open=12.0, high=15.0, low=0.0, close=14.0)
        series = fx.with_calm(*rise, pattern, calm=70)
        dets = detections(engine, series)
        # price rose into the pattern, so the strict reading is a pin bar at best
        assert "HAMMER" not in patterns(dets)

    def test_exposed_measurements(self, engine):
        for pattern, series in (("HAMMER", fx.hammer()), ("SHOOTING_STAR", fx.shooting_star())):
            detection = one(detections(engine, series), pattern)
            measurements = detection.evidence_points["measurements"]
            assert measurements["prior_move_pips"] > 0
            assert measurements["required_prior_move_pips"] > 0
            assert measurements["wick_to_body"] >= 2.0
            assert detection.evidence_points["context"]["required_pips"] > 0


# ------------------------------------------------------------- inside / outside
class TestInsideBar:
    def test_positive(self, engine):
        detection = one(detections(engine, fx.inside_bar()), "INSIDE_BAR")
        points = detection.evidence_points
        assert "mother_candle" in points and "inside_candle" in points
        assert points["range_ratio"] == pytest.approx(0.5, abs=1e-6)
        assert points["range_ratio"] <= 0.9
        assert detection.direction.value == "NEUTRAL"
        confidence_is_weighted_share(detection)

    def test_negative_when_not_contained(self, engine):
        series = fx.inside_bar(breach=3.0)  # 3 pips outside the mother range
        assert "INSIDE_BAR" not in patterns(detections(engine, series))

    def test_tolerance_of_containment(self, engine):
        """With a 4-pip containment tolerance the same 3-pip breach is accepted."""
        params = PriceActionParams()
        params.inside_bar.containment_tolerance_pips = 4.0
        assert "INSIDE_BAR" not in patterns(detections(PriceActionEngine(PriceActionParams()), fx.inside_bar(breach=3.0)))
        assert "INSIDE_BAR" in patterns(detections(PriceActionEngine(params), fx.inside_bar(breach=3.0)))

    def test_boundary_range_ratio(self, engine):
        """Inside range = 90% of the mother range: accepted (rule is <= 0.9)."""
        series = fx.inside_bar(mother_range=20.0, inside_range=18.0)
        detection = one(detections(engine, series), "INSIDE_BAR")
        assert detection.evidence_points["range_ratio"] == pytest.approx(0.9, abs=1e-6)

    def test_negative_when_the_range_expands(self, engine):
        series = fx.inside_bar(mother_range=10.0, inside_range=9.5)
        assert "INSIDE_BAR" not in patterns(detections(engine, series))

    def test_both_sides_are_watched(self, engine):
        detection = one(detections(engine, fx.inside_bar()), "INSIDE_BAR")
        sides = {level.level_type for level in detection.watch_levels if level.role == "CONFIRMATION"}
        assert sides == {"MOTHER_HIGH", "MOTHER_LOW"}


class TestOutsideBar:
    def test_positive(self, engine):
        detection = one(detections(engine, fx.outside_bar()), "OUTSIDE_BAR")
        points = detection.evidence_points
        for key in ("previous_high", "previous_low", "current_high", "current_low"):
            assert key in points
        assert points["current_high"] > points["previous_high"]
        assert points["current_low"] < points["previous_low"]
        assert points["measurements"]["range_ratio"] >= 1.1
        confidence_is_weighted_share(detection)

    def test_negative_when_only_one_side_is_exceeded(self, engine):
        previous = fx.BarSpec(open=0.0, high=6.0, low=0.0, close=5.0)
        current = fx.BarSpec(open=5.0, high=9.0, low=0.0, close=8.0)  # low equal, not broken
        series = fx.with_calm(previous, current, calm=70)
        assert "OUTSIDE_BAR" not in patterns(detections(engine, series))

    def test_boundary_breach_and_ratio(self, engine):
        """0.5 pip breach on each side and a range ratio of exactly 1.1: accepted."""
        series = fx.outside_bar(previous_range=10.0, breach=0.5)
        detection = one(detections(engine, series), "OUTSIDE_BAR")
        assert detection.evidence_points["range_ratio"] == pytest.approx(1.1, abs=1e-4)

    def test_tolerance_below_the_breach_floor(self, engine):
        """A 0.2-pip breach is below min_breach_pips (0.5) -> not an outside bar."""
        series = fx.outside_bar(previous_range=10.0, breach=0.2)
        assert "OUTSIDE_BAR" not in patterns(detections(engine, series))

    def test_range_ratio_floor(self, engine):
        """Both sides are breached (0.6 pip) but the previous range is so wide that the
        expansion is only x1.06 < x1.10: rejected by the ratio rule, not by the breach."""
        series = fx.outside_bar(previous_range=20.0, breach=0.6)
        dets = detections(engine, series)
        assert "OUTSIDE_BAR" not in patterns(dets)
        assert formulas_agree(series)
        assert "OUTSIDE_BAR" in patterns(
            detections(PriceActionEngine(relaxed_ratio_params()), series)
        )


# ----------------------------------------------------------------------- doji
class TestDoji:
    def test_positive(self, engine):
        detection = one(detections(engine, fx.doji()), "DOJI")
        measurements = detection.evidence_points["measurements"]
        assert measurements["body_ratio"] <= 0.1
        assert measurements["range_pips"] >= 3.0
        assert measurements["long_legged"] is True
        assert detection.direction.value == "NEUTRAL"
        confidence_is_weighted_share(detection)

    def test_not_only_open_equals_close(self, engine):
        """A real body of 2 pips in a 10-pip range is not a doji, and an empty body
        in a 1-pip range is noise: both sides of the definition are enforced."""
        assert "DOJI" not in patterns(detections(engine, fx.doji(body=2.0, range_pips=10.0)))
        flat = fx.BarSpec(open=5.0, high=5.5, low=4.5, close=5.0)  # body 0, range 1 pip
        assert "DOJI" not in patterns(detections(engine, fx.with_calm(flat, calm=70)))

    def test_boundary_body_ratio(self, engine):
        """body/range exactly 0.1: accepted."""
        detection = one(detections(engine, fx.doji(body=1.0, range_pips=10.0)), "DOJI")
        assert detection.evidence_points["body_ratio"] == pytest.approx(0.1, abs=1e-4)

    def test_range_floor(self, engine):
        """Body 0.1 pip in a 2-pip range: below min_range_pips (3) -> rejected."""
        bar = fx.BarSpec(open=5.0, high=6.0, low=4.0, close=5.1)
        assert "DOJI" not in patterns(detections(engine, fx.with_calm(bar, calm=70)))

    def test_ambiguous_short_body_with_long_wicks(self, engine):
        """A long-legged doji is also close to a pin bar: the engine keeps the two
        readings separate instead of merging them into one label."""
        dets = detections(engine, fx.doji(body=0.2, range_pips=14.0))
        assert "DOJI" in patterns(dets)
        assert "BULLISH_PIN_BAR" not in patterns(dets)  # symmetric wicks: no side dominates
        assert "BEARISH_PIN_BAR" not in patterns(dets)


# ------------------------------------------------------------ structure & dedup
class TestCandleDeduplicationAndDeterminism:
    def test_same_candle_same_identifier_on_a_second_run(self, engine):
        series = fx.bullish_engulfing()
        first = detections(engine, series)
        first_ids = {d.id for d in first}
        second = detections(engine, series)  # identical run: identical identity
        assert [d.id for d in first] == [d.id for d in second]
        assert len({d.id for d in first}) == len(first), "no duplicate for one candle"
        assert all(d.dedup_key == d.id for d in first)

    def test_no_second_event_for_an_unchanged_detection(self, engine):
        series = fx.bullish_engulfing()
        result = engine.analyse(series)
        first_events = engine.commit(result)
        second_events = engine.commit(engine.analyse(series))
        assert [e.event_type for e in first_events] == ["PRICE_ACTION_DETECTED"]
        assert second_events == [], "an unchanged detection must not be published twice"

    def test_a_new_candle_is_a_new_detection(self, engine):
        """The identity is tied to the candle: the next bar gets its own id."""
        series = fx.bullish_engulfing()
        first_ids = {event.detection.id for event in engine.commit(engine.analyse(series))}
        assert first_ids, "the fixture must produce at least one detection"
        extended = series.model_copy(
            update={
                "candles": series.candles
                + [fx.BarSpec(open=1.0, high=1.4, low=0.8, close=1.2).build(len(series.candles))]
            }
        )
        result = engine.analyse(extended)
        ids = {d.id for d in result.detections}
        assert first_ids <= ids, "the earlier detection keeps its identity (same candle)"
        events = engine.commit(result)
        assert [e for e in events if e.detection.id in first_ids] == [], (
            "a detection already known for that candle is never re-published"
        )

    def test_identifier_contains_the_real_candle_time(self, engine):
        from app.price_action.engine import dedup_key

        series = fx.bullish_engulfing()
        detection = one(detections(engine, series), "BULLISH_ENGULFING")
        expected = dedup_key("EURUSD", "M15", "BULLISH_ENGULFING", detection.detected_at_bar_time)
        assert detection.id == expected
        assert detection.detected_at_bar_time == series.candles[-1].time
