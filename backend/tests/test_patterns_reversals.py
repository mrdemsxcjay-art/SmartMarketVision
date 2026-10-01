"""Chartist engine - reversal formations (Double Top / Bottom, Head & Shoulders).

Every test uses a synthetic fixture built explicitly here; the application itself
never generates prices. Each case checks a *measurable* rule of the detector:
tolerance, minimum depth, separation, intervening extremes, trend context.
"""

from __future__ import annotations

import pytest

from tests.pattern_fixtures import build_series, double_bottom, double_top, head_shoulders
from tests.pattern_fixtures import BPL


def patterns(result) -> list[str]:
    return [detection.pattern for detection in result.detections]


def find(result, pattern: str):
    for detection in result.detections:
        if detection.pattern == pattern:
            return detection
    raise AssertionError(f"{pattern} not detected (found: {patterns(result)})")


class TestDoubleTop:
    def test_detects_a_clean_double_top(self, engine):
        result = engine.analyse(double_top().series)
        detection = find(result, "DOUBLE_TOP")
        assert detection.direction.value == "BEARISH"
        assert detection.status.value == "DETECTED"
        assert 0 < detection.confidence <= 100

    def test_evidence_holds_the_measurable_facts(self, engine):
        detection = find(engine.analyse(double_top().series), "DOUBLE_TOP")
        joined = " | ".join(detection.evidence)
        assert "Ecart entre les deux" in joined
        assert "Profondeur" in joined
        assert "Separation temporelle" in joined
        assert "Neckline" in joined
        points = detection.evidence_points
        assert points["peak_1"]["price"] == pytest.approx(1.11012, abs=1e-5)
        assert points["peak_2"]["price"] == pytest.approx(1.11007, abs=1e-5)
        assert points["valley"]["price"] == pytest.approx(1.10738, abs=1e-5)
        assert points["neckline"]["price"] == pytest.approx(1.10738, abs=1e-5)
        measurements = points["measurements"]
        assert measurements["time_separation_bars"] == 28
        assert measurements["price_difference_pips"] == pytest.approx(0.5, abs=0.01)
        assert measurements["tolerance_pips"] == 5.0

    def test_coordinates_are_drawable_and_match_the_pivots(self, engine):
        detection = find(engine.analyse(double_top().series), "DOUBLE_TOP")
        assert len(detection.coordinates) >= 3
        times = [point.time for point in detection.coordinates]
        assert times == sorted(times)
        for point in detection.coordinates:
            assert point.price > 0
        labels = [level.label for level in detection.drawing.levels]
        assert "NECKLINE" in labels
        # the two peaks and the valley are drawn as markers with their roles
        markers = detection.drawing.markers
        assert len(markers) >= 3

    def test_peaks_further_apart_than_the_tolerance_are_rejected(self, engine):
        result = engine.analyse(double_top(tolerance_pips=6.0).series)
        assert "DOUBLE_TOP" not in patterns(result)

    def test_a_shallow_valley_is_rejected(self, engine):
        result = engine.analyse(double_top(depth_pips=5).series)
        assert "DOUBLE_TOP" not in patterns(result)

    def test_an_intervening_higher_peak_breaks_the_pattern(self, engine):
        # peak, valley, HIGHER peak, valley, peak -> no clean double top
        series = build_series(
            [1.0960, 1.1000, 1.1040, 1.1100, 1.1075, 1.1120, 1.1060, 1.1100, 1.1080],
            bars_per_leg=BPL,
        )
        assert "DOUBLE_TOP" not in patterns(engine.analyse(series))

    def test_minimum_separation_is_enforced(self, engine):
        # the fixture's peaks are 28 bars apart; demanding more rejects it
        engine.params.double_top_bottom.min_peak_separation_bars = 40
        assert "DOUBLE_TOP" not in patterns(engine.analyse(double_top().series))

    def test_a_single_peak_is_never_a_double_top(self, engine):
        series = build_series([1.0960, 1.1050, 1.0980, 1.1080, 1.1000], bars_per_leg=BPL)
        assert "DOUBLE_TOP" not in patterns(engine.analyse(series))

    def test_confidence_comes_from_explicit_criteria_only(self, engine):
        detection = find(engine.analyse(double_top().series), "DOUBLE_TOP")
        assert detection.confidence_factors, "confidence must list its criteria"
        total_weight = sum(factor.weight for factor in detection.confidence_factors)
        earned = sum(factor.weight for factor in detection.confidence_factors if factor.passed)
        assert detection.confidence == pytest.approx(100 * earned / total_weight, abs=0.6)
        for factor in detection.confidence_factors:
            assert factor.criterion and factor.detail


class TestDoubleBottom:
    def test_detects_a_clean_double_bottom(self, engine):
        detection = find(engine.analyse(double_bottom().series), "DOUBLE_BOTTOM")
        assert detection.direction.value == "BULLISH"
        points = detection.evidence_points
        assert points["peak_1"]["type"] == "LOW"
        assert points["peak_2"]["type"] == "LOW"
        assert points["valley"]["type"] == "HIGH"

    def test_peaks_further_apart_than_the_tolerance_are_rejected(self, engine):
        series = build_series([1.1140, 1.1100, 1.1060, 1.1000, 1.1025, 1.0992, 1.1030], bars_per_leg=BPL)
        assert "DOUBLE_BOTTOM" not in patterns(engine.analyse(series))


class TestHeadAndShoulders:
    def test_detects_a_classic_head_and_shoulders(self, engine):
        detection = find(engine.analyse(head_shoulders().series), "HEAD_SHOULDERS")
        assert detection.direction.value == "BEARISH"
        roles = detection.evidence_points["pivots"]
        assert roles["HEAD"]["price"] > roles["LEFT_SHOULDER"]["price"]
        assert roles["HEAD"]["price"] > roles["RIGHT_SHOULDER"]["price"]
        assert roles["LEFT_SHOULDER"]["index"] < roles["HEAD"]["index"] < roles["RIGHT_SHOULDER"]["index"]
        assert detection.evidence_points["neckline"]["slope_per_bar"] is not None
        assert "Tete plus marquee" in " | ".join(detection.evidence)

    def test_detects_an_inverse_head_and_shoulders(self, engine):
        detection = find(engine.analyse(head_shoulders(inverse=True).series), "INVERSE_HEAD_SHOULDERS")
        assert detection.direction.value == "BULLISH"
        roles = detection.evidence_points["pivots"]
        assert roles["HEAD"]["price"] < roles["LEFT_SHOULDER"]["price"]
        assert roles["HEAD"]["price"] < roles["RIGHT_SHOULDER"]["price"]

    def test_a_head_that_does_not_dominate_is_rejected(self, engine):
        # head only 5 pips above the shoulders, while the minimum prominence is
        # max(6 pips, 0.6 ATR): the formation is not pronounced enough
        series = build_series(
            [1.1040, 1.1000, 1.1045, 1.1080, 1.1032, 1.1085, 1.1035, 1.1082, 1.1050],
            bars_per_leg=BPL,
        )
        assert "HEAD_SHOULDERS" not in patterns(engine.analyse(series))

    def test_very_different_shoulders_are_rejected(self, engine):
        # right shoulder 40 pips above the left one, tolerance is 8 pips
        series = build_series(
            [1.1040, 1.1000, 1.1045, 1.1080, 1.1032, 1.1140, 1.1035, 1.1122, 1.1050],
            bars_per_leg=BPL,
        )
        assert "HEAD_SHOULDERS" not in patterns(engine.analyse(series))

    def test_a_pattern_without_prior_trend_is_rejected(self, engine):
        """A rectangle cannot contain a head & shoulders: there is no advance."""
        flat_ish = build_series(
            [1.1040, 1.1036, 1.1042, 1.1045, 1.1038, 1.1041, 1.1039],
            bars_per_leg=BPL,
        )
        assert "HEAD_SHOULDERS" not in patterns(engine.analyse(flat_ish))

    def test_trend_context_is_reported_in_the_evidence(self, engine):
        detection = find(engine.analyse(head_shoulders().series), "HEAD_SHOULDERS")
        assert "Contexte" in " | ".join(detection.evidence)
        assert detection.evidence_points["measurements"]["prior_trend_pips"] > 0
