"""Chartist engine - triangle, wedge and channel detectors.

The rules under test: a triangle is never declared from two points per line, the
boundaries must really converge, the apex must not be behind us, and the shape
must narrow measurably across the formation.
"""

from __future__ import annotations

import pytest

from tests.pattern_fixtures import (
    BPL,
    ascending_triangle,
    build_series,
    channel,
    descending_triangle,
    falling_wedge,
    rising_wedge,
    symmetrical_triangle,
)


def patterns(result) -> list[str]:
    return [detection.pattern for detection in result.detections]


def find(result, pattern: str):
    for detection in result.detections:
        if detection.pattern == pattern:
            return detection
    raise AssertionError(f"{pattern} not detected (found: {patterns(result)})")


class TestTriangles:
    def test_ascending_triangle(self, engine):
        detection = find(engine.analyse(ascending_triangle().series), "ASCENDING_TRIANGLE")
        assert detection.direction.value == "BULLISH"
        touches_upper = detection.evidence_points["touches_upper"]
        touches_lower = detection.evidence_points["touches_lower"]
        assert len(touches_upper) >= 3, "a triangle needs at least three touches per line"
        assert len(touches_lower) >= 3
        assert detection.evidence_points["measurements"]["upper_slope_pips_per_bar"] == pytest.approx(0.0, abs=0.05)
        assert detection.evidence_points["measurements"]["lower_slope_pips_per_bar"] > 0
        assert "Statut : triangle en cours" in " | ".join(detection.evidence)

    def test_descending_triangle(self, engine):
        detection = find(engine.analyse(descending_triangle().series), "DESCENDING_TRIANGLE")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["measurements"]["upper_slope_pips_per_bar"] < 0
        assert detection.evidence_points["measurements"]["lower_slope_pips_per_bar"] == pytest.approx(0.0, abs=0.05)

    def test_symmetrical_triangle(self, engine):
        detection = find(engine.analyse(symmetrical_triangle().series), "SYMMETRICAL_TRIANGLE")
        assert detection.direction.value == "NEUTRAL"
        measurements = detection.evidence_points["measurements"]
        assert measurements["upper_slope_pips_per_bar"] < 0 < measurements["lower_slope_pips_per_bar"]
        assert measurements["contraction"] > 0.2

    def test_two_points_per_line_are_not_a_triangle(self, engine):
        """Three pivots only: no line can be validated, so nothing is declared."""
        series = build_series([1.1040, 1.1000, 1.1100, 1.1050, 1.1090], bars_per_leg=BPL)
        result = engine.analyse(series)
        assert not [p for p in patterns(result) if "TRIANGLE" in p]

    def test_minimum_touches_can_be_raised(self, engine):
        engine.params.triangle.min_touches_per_line = 4
        assert "ASCENDING_TRIANGLE" not in patterns(engine.analyse(ascending_triangle().series))

    def test_parallel_boundaries_are_not_a_triangle(self, engine):
        # resistance and support rising at the same speed: no convergence
        series = build_series(
            [1.1040, 1.1000, 1.1100, 1.1060, 1.1160, 1.1120, 1.1220, 1.1190],
            bars_per_leg=BPL,
        )
        assert "SYMMETRICAL_TRIANGLE" not in patterns(engine.analyse(series))

    def test_breakout_level_is_the_touched_boundary(self, engine):
        detection = find(engine.analyse(ascending_triangle().series), "ASCENDING_TRIANGLE")
        watched = [(level.level_type, level.price, level.direction.value) for level in detection.watch_levels]
        assert watched == [("RESISTANCE", pytest.approx(1.11012, abs=1e-5), "BULLISH")]


class TestWedges:
    def test_rising_wedge(self, engine):
        detection = find(engine.analyse(rising_wedge().series), "RISING_WEDGE")
        assert detection.direction.value == "BEARISH"
        measurements = detection.evidence_points["measurements"]
        assert measurements["upper_slope_pips_per_bar"] > 0
        assert measurements["lower_slope_pips_per_bar"] > measurements["upper_slope_pips_per_bar"]
        assert "convergent" in " | ".join(detection.evidence)

    def test_falling_wedge(self, engine):
        detection = find(engine.analyse(falling_wedge().series), "FALLING_WEDGE")
        assert detection.direction.value == "BULLISH"
        measurements = detection.evidence_points["measurements"]
        assert measurements["upper_slope_pips_per_bar"] < 0
        assert measurements["lower_slope_pips_per_bar"] < 0
        assert measurements["contraction"] > 0.2

    def test_two_touches_per_line_are_rejected(self, engine):
        """A wedge from four pivots only: the boundaries are under-determined."""
        series = build_series([1.1180, 1.1200, 1.1000, 1.1208, 1.1053, 1.1150], bars_per_leg=BPL)
        result = engine.analyse(series)
        assert not [p for p in patterns(result) if "WEDGE" in p]

    def test_a_diverging_shape_is_not_a_wedge(self, engine):
        # the boundaries open up instead of converging
        series = build_series(
            [1.1000, 1.1050, 1.1010, 1.1100, 1.1040, 1.1150, 1.1070, 1.1200],
            bars_per_leg=BPL,
        )
        result = engine.analyse(series)
        assert not [p for p in patterns(result) if "WEDGE" in p]


class TestChannel:
    def test_detects_a_rising_channel(self, engine):
        detection = find(engine.analyse(channel().series), "CHANNEL")
        assert detection.direction.value == "BULLISH"
        measurements = detection.evidence_points["measurements"]
        assert measurements["upper_touches"] >= 3
        assert measurements["lower_touches"] >= 3
        assert measurements["slope_gap_relative"] <= 0.35
        assert measurements["slope_pips_per_bar_upper"] > 0
        assert "regression" not in " ".join(detection.notes).lower()

    def test_a_channel_breaks_both_ways(self, engine):
        detection = find(engine.analyse(channel().series), "CHANNEL")
        directions = {level.direction.value for level in detection.watch_levels}
        assert directions == {"BULLISH", "BEARISH"}

    def test_a_converging_shape_is_not_a_channel(self, engine):
        result = engine.analyse(symmetrical_triangle().series)
        assert "CHANNEL" not in patterns(result)

    def test_a_flat_rectangle_is_not_a_channel(self, engine):
        """Horizontal boundaries are a rectangle, not a channel."""
        series = build_series(
            [1.1060, 1.1050, 1.1000, 1.1050, 1.1000, 1.1050, 1.1000, 1.1050, 1.1020],
            bars_per_leg=BPL,
        )
        assert "CHANNEL" not in patterns(engine.analyse(series))

    def test_width_drift_limit_rejects_a_flaring_shape(self, engine):
        series = build_series(
            [1.0980, 1.1000, 1.1080, 1.1010, 1.1130, 1.1030, 1.1200, 1.1060, 1.1280],
            bars_per_leg=BPL,
        )
        assert "CHANNEL" not in patterns(engine.analyse(series))
