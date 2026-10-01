"""The 16 reference scenarios, run through the engine exactly like production.

Each scenario is a synthetic OHLC series (tests only - the application itself
never generates prices) built so that the *measurable* conditions of one pattern
are satisfied. The engine must find that pattern, with the right direction, and
must be reproducible: analysing the same series twice gives the same result.
"""

from __future__ import annotations

import pytest

from tests.pattern_fixtures import ALL_POSITIVE_SCENARIOS, build_series, flat_noise


def ids(scenario) -> str:
    return scenario.expected_pattern


@pytest.mark.parametrize("scenario", ALL_POSITIVE_SCENARIOS, ids=ids)
def test_reference_scenario_is_detected(engine, scenario):
    result = engine.analyse(scenario.series)
    found = {detection.pattern: detection for detection in result.detections}
    assert scenario.expected_pattern in found, (
        f"{scenario.description}: {scenario.expected_pattern} missing "
        f"(detected: {sorted(found)}; notes: {result.notes})"
    )
    detection = found[scenario.expected_pattern]
    assert detection.direction.value == scenario.expected_direction
    assert detection.evidence, "every detection must explain itself"
    assert detection.coordinates, "every detection must be drawable"
    assert 0 < detection.confidence <= 100


@pytest.mark.parametrize("scenario", ALL_POSITIVE_SCENARIOS, ids=ids)
def test_reference_scenario_is_reproducible(engine, scenario):
    first = engine.analyse(scenario.series)
    second = engine.analyse(scenario.series)
    assert [d.id for d in first.detections] == [d.id for d in second.detections]
    assert [d.confidence for d in first.detections] == [d.confidence for d in second.detections]


class TestAbsenceOfFictionalDetection:
    """Cases where the engine must stay silent - the real anti over-detection net."""

    def test_a_monotonic_rise_contains_no_chartist_pattern(self, engine):
        series = build_series([1.0900 + i * 0.0020 for i in range(8)], bars_per_leg=14)
        result = engine.analyse(series)
        assert result.detections == []

    def test_a_monotonic_fall_contains_no_chartist_pattern(self, engine):
        series = build_series([1.1100 - i * 0.0020 for i in range(8)], bars_per_leg=14)
        assert engine.analyse(series).detections == []

    def test_a_series_below_the_minimum_bar_count_is_refused(self, engine):
        series = build_series([1.1000, 1.1010, 1.0995, 1.1005], bars_per_leg=5)
        result = engine.analyse(series)
        assert result.detections == []
        assert any("not enough closed bars" in note for note in result.notes)

    def test_open_candles_are_never_analysed(self, engine):
        series = build_series([1.0960, 1.1000, 1.1040, 1.1100, 1.1075, 1.10995, 1.1085], bars_per_leg=14)
        closed = series
        opened = series.model_copy(
            update={"candles": [*series.candles[:-1], series.candles[-1].model_copy(update={"closed": False})]}
        )
        assert engine.analyse(opened).bars_analyzed == engine.analyse(closed).bars_analyzed - 1

    def test_a_noise_series_never_produces_an_unexplained_detection(self, engine):
        """Random-walk candles: whatever is found must be fully explained and
        reproducible - the engine never invents a pattern out of nothing."""
        result = engine.analyse(flat_noise(200, 9, 17))
        for detection in result.detections:
            assert detection.evidence and detection.evidence_points
            assert detection.coordinates
            assert detection.parameters, "a detection without its parameters is not auditable"
            assert detection.confidence == pytest.approx(
                100
                * sum(f.weight for f in detection.confidence_factors if f.passed)
                / sum(f.weight for f in detection.confidence_factors),
                abs=0.6,
            )
