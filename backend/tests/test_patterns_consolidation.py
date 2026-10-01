"""Chartist engine - rectangle, support/resistance levels and flags/pennants.

Rectangle: two horizontal levels, several touches, a real consolidation box.
Levels: clustering of real pivots, with a measurable strength.
Flags: a prior impulse is mandatory - a small consolidation alone is never a flag.
"""

from __future__ import annotations

import pytest

from tests.pattern_fixtures import (
    BPL,
    bear_flag,
    build_series,
    bull_flag,
    rectangle,
    support_resistance,
)


def patterns(result) -> list[str]:
    return [detection.pattern for detection in result.detections]


def level(detection, label: str) -> float:
    """Read a drawn level by label (the drawing is what the dashboard renders)."""
    for item in detection.drawing.levels:
        if item.label == label:
            return item.price
    raise AssertionError(f"level {label} not in the drawing: {[l.label for l in detection.drawing.levels]}")


def find(result, pattern: str):
    for detection in result.detections:
        if detection.pattern == pattern:
            return detection
    raise AssertionError(f"{pattern} not detected (found: {patterns(result)})")


class TestRectangle:
    def test_detects_a_horizontal_rectangle(self, engine):
        detection = find(engine.analyse(rectangle().series), "RECTANGLE")
        points = detection.evidence_points
        assert points["resistance_price"] == pytest.approx(1.10512, abs=1e-4)
        assert points["support_price"] == pytest.approx(1.09988, abs=1e-4)
        assert len(points["touches_resistance"]) >= 2
        assert len(points["touches_support"]) >= 2
        assert points["measurements"]["height_pips"] > 12
        assert level(detection, "RESISTANCE") > level(detection, "SUPPORT")

    def test_the_box_is_drawn_as_a_zone(self, engine):
        detection = find(engine.analyse(rectangle().series), "RECTANGLE")
        assert detection.drawing.zones, "the consolidation must be drawable as a zone"
        zone = detection.drawing.zones[0]
        assert zone.price_top > zone.price_bottom
        assert zone.time_end > zone.time_start

    def test_a_sloped_support_is_not_a_rectangle(self, engine):
        """A rising support belongs to a triangle or a channel, not a rectangle."""
        assert "RECTANGLE" not in patterns(engine.analyse(ascending_triangle_series()))

    def test_a_too_small_box_is_rejected(self, engine):
        engine.params.rectangle.min_height_pips = 120
        assert "RECTANGLE" not in patterns(engine.analyse(rectangle().series))

    def test_minimum_touches_are_enforced(self, engine):
        """The fixture touches each side three times: demanding four rejects it."""
        engine.params.rectangle.min_touches_per_side = 4
        assert "RECTANGLE" not in patterns(engine.analyse(rectangle().series))


class TestSupportResistance:
    def test_levels_come_from_pivot_clustering(self, engine):
        result = engine.analyse(support_resistance().series)
        resistance = find(result, "RESISTANCE")
        support = find(result, "SUPPORT")
        for detection, expected in ((resistance, 1.11012), (support, 1.10188)):
            points = detection.evidence_points
            assert points["price"] == pytest.approx(expected, abs=1e-4)
            assert points["touch_count"] >= 2
            assert len(points["touches"]) == points["touch_count"]
            assert points["first_touch"]["time"] <= points["last_touch"]["time"]
            assert 0 <= points["strength"] <= 100

    def test_strength_is_computed_from_measurable_parts(self, engine):
        detection = find(engine.analyse(support_resistance().series), "RESISTANCE")
        details = detection.evidence_points["strength_details"]
        assert len(details) == 3
        assert any("touches" in line for line in details)
        assert any("ATR" in line for line in details)

    def test_a_level_broken_and_left_behind_is_not_reported(self, engine):
        """After a decisive close beyond a level, that level is stale."""
        series = build_series(
            [1.1040, 1.1100, 1.1040, 1.1100, 1.1040, 1.1130, 1.1180],
            bars_per_leg=BPL,
        )
        result = engine.analyse(series)
        resistance_levels = [
            d for d in result.detections if d.pattern == "RESISTANCE" and d.evidence_points["price"] > 1.109
        ]
        assert not resistance_levels, "a broken level must not be advertised as live"

    def test_a_level_untouched_for_too_long_is_dropped(self, engine):
        """A level nobody has traded for weeks is history, not a live level."""
        engine.params.levels.max_bars_since_touch = 5
        assert "RESISTANCE" not in patterns(engine.analyse(support_resistance().series))
        assert "SUPPORT" not in patterns(engine.analyse(support_resistance().series))

    def test_minimum_touches_filter(self, engine):
        engine.params.levels.min_touches = 4
        assert "RESISTANCE" not in patterns(engine.analyse(support_resistance().series))


class TestFlagsAndPennants:
    def test_bull_flag(self, engine):
        detection = find(engine.analyse(bull_flag().series), "BULL_FLAG")
        assert detection.direction.value == "BULLISH"
        pole = detection.evidence_points["pole"]
        box = detection.evidence_points["consolidation"]
        assert pole["pips"] > 50
        assert box["bars"] >= 30
        assert detection.evidence_points["retracement_ratio"] < 0.6
        assert "Continuation attendue : BULLISH" in " | ".join(detection.evidence)

    def test_bear_flag(self, engine):
        detection = find(engine.analyse(bear_flag().series), "BEAR_FLAG")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["pole"]["pips"] > 50

    def test_bull_pennant_requires_converging_boundaries(self, engine):
        detection = find(engine.analyse(bull_flag(kind="PENNANT").series), "BULL_PENNANT")
        assert detection.evidence_points["shape"] == "PENNANT"
        assert detection.evidence_points["measurements"]["contraction"] > 0.2

    def test_bear_pennant(self, engine):
        detection = find(engine.analyse(bear_flag(kind="PENNANT").series), "BEAR_PENNANT")
        assert detection.direction.value == "BEARISH"

    def test_a_consolidation_without_a_pole_is_not_a_flag(self, engine):
        """Flat drift only: no impulse before it, so no continuation pattern."""
        series = build_series(
            [1.1000, 1.1004, 1.1002, 1.1005, 1.1003, 1.1006, 1.1004, 1.1007],
            bars_per_leg=BPL,
        )
        result = engine.analyse(series)
        assert not [p for p in patterns(result) if "FLAG" in p or "PENNANT" in p]

    def test_a_consolidation_wider_than_the_pole_is_rejected(self, engine):
        engine.params.flags.max_width_pole_ratio = 0.05
        result = engine.analyse(bull_flag().series)
        assert "BULL_FLAG" not in patterns(result)

    def test_a_deep_retracement_is_rejected(self, engine):
        engine.params.flags.max_retrace_ratio = 0.1
        result = engine.analyse(bull_flag().series)
        assert "BULL_FLAG" not in patterns(result)

    def test_a_too_short_consolidation_is_rejected(self, engine):
        engine.params.flags.consolidation_min_bars = 60
        result = engine.analyse(bull_flag().series)
        assert "BULL_FLAG" not in patterns(result)

    def test_the_breakout_level_is_the_consolidation_edge(self, engine):
        detection = find(engine.analyse(bull_flag().series), "BULL_FLAG")
        watched = [(level.level_type, level.direction.value) for level in detection.watch_levels]
        assert watched == [("CONSOLIDATION_HIGH", "BULLISH")]
        assert detection.evidence_points["consolidation"]["high"] == level(detection, "CONSOLIDATION_HIGH")


def ascending_triangle_series():
    """A rising support with a flat resistance: a rectangle detector must refuse it."""
    return build_series(
        [1.1040, 1.1000, 1.1100, 1.1030, 1.1100, 1.1060, 1.1100, 1.1090],
        bars_per_leg=BPL,
    )
