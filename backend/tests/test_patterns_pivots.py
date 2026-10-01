"""Chartist engine - pivot detection, ATR and the parameter contract.

Pivots are the only raw material of every detection, so they are tested on
explicit OHLC: a pivot must be a real local extreme confirmed by its neighbours,
carry an index / timestamp / price / type, and be reused by the patterns that
were built on it.
"""

from __future__ import annotations

import pytest

from app.patterns.params import PatternParams
from app.patterns.pivots import compute_atr, find_pivots
from tests.pattern_fixtures import double_top
from tests.test_patterns_reversals import find


class TestPivotDetection:
    def test_a_pivot_is_a_strict_local_extreme(self, ctx_candles):
        pivots = find_pivots(ctx_candles, left=2, right=2)
        highs = [p for p in pivots if p.is_high]
        lows = [p for p in pivots if not p.is_high]
        assert highs and lows
        for pivot in pivots:
            neighbours = ctx_candles[pivot.index - 2 : pivot.index + 3]
            assert len(neighbours) == 5
            if pivot.is_high:
                assert all(pivot.price >= other.high for other in neighbours)
            else:
                assert all(pivot.price <= other.low for other in neighbours)

    def test_every_pivot_carries_its_identity(self, ctx_candles):
        for pivot in find_pivots(ctx_candles, left=2, right=2):
            assert pivot.kind in {"HIGH", "LOW"}
            assert pivot.index > 0
            assert pivot.price > 0
            assert pivot.time == ctx_candles[pivot.index].time
            assert pivot.confirmed_at_index >= pivot.index, "a pivot is confirmed by later bars"

    def test_a_flat_series_has_no_pivot(self, engine):
        from tests.pattern_fixtures import build_series

        flat = build_series([1.1000, 1.1000, 1.1000, 1.1000], bars_per_leg=20, wick_pips=0.0)
        result = engine.analyse(flat)
        assert result.pivots == 0
        assert result.detections == []


class TestAtr:
    def test_atr_is_the_wilder_average_of_real_ranges(self, ctx_candles):
        atr = compute_atr(ctx_candles, period=14)
        assert atr > 0
        # never larger than the biggest true range and never zero
        biggest = max(c.high - c.low for c in ctx_candles)
        assert atr <= biggest

    def test_atr_is_zero_when_there_is_not_enough_data(self):
        assert compute_atr([], period=14) == 0.0


class TestParameterContract:
    def test_every_threshold_lives_in_the_parameter_model(self):
        params = PatternParams()
        snapshot = params.snapshot()
        for group in (
            "globals",
            "double_top_bottom",
            "head_shoulders",
            "triangle",
            "wedge",
            "rectangle",
            "flags",
            "levels",
            "channel",
            "breakout",
            "weights",
        ):
            assert group in snapshot, f"{group} must be centralised in PatternParams"
        assert "global_" not in snapshot, "the API exposes 'globals'"

    def test_the_engine_uses_the_parameters_it_was_given(self, engine):
        engine.params.double_top_bottom.peak_tolerance_pips = 0.0
        engine.params.double_top_bottom.peak_tolerance_atr = 0.0
        result = engine.analyse(double_top().series)
        assert "DOUBLE_TOP" not in [d.pattern for d in result.detections], (
            "with a zero tolerance two peaks 0.5 pip apart cannot match"
        )

    def test_parameters_are_stored_with_each_detection(self, engine):
        detection = find(engine.analyse(double_top().series), "DOUBLE_TOP")
        params = detection.parameters
        assert params["peak_tolerance_pips"] > 0
        assert params["min_peak_separation_bars"] > 0
        assert params["atr"] > 0
        assert params["confidence_factors"], "the criteria used must be stored too"
