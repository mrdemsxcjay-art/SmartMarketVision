"""Market-structure tests: pivots, HH/HL/LH/LL labels and trend classification.

Candles are built from explicit ``(high, low)`` ranges so each swing is
unambiguous. This is test fixture data, never used by the application.
"""

from __future__ import annotations

import pytest

from app.schemas.market import Timeframe
from app.schemas.structure import StructuralTrend, SwingKind, SwingLabel
from app.services.structure import (
    analyse_structure,
    classify_trend,
    find_swings,
    label_swings,
    recent_labels,
)

from tests.conftest import candles_from_ranges, make_candles

# (high, low) sequences: peak / trough / peak / trough / peak
BULLISH = [
    (1.01, 1.000),   # start
    (1.10, 1.020),   # swing high 1
    (1.06, 1.010),   # swing low 1
    (1.13, 1.050),   # higher high
    (1.09, 1.045),   # higher low
    (1.16, 1.060),   # higher high
    (1.12, 1.080),
]
BEARISH = [
    (1.20, 1.190),
    (1.18, 1.100),   # swing low 1  (mirror of the bullish swing high)
    (1.19, 1.140),   # lower high
    (1.15, 1.070),   # lower low
    (1.155, 1.110),
    (1.14, 1.040),   # lower high
    (1.12, 1.080),
]
RANGE_EXPANDING = [
    (1.07, 1.06),
    (1.10, 1.07),   # swing high
    (1.09, 1.05),   # swing low
    (1.15, 1.08),   # higher high
    (1.12, 1.00),   # lower low  -> higher high + lower low = expansion
    (1.16, 1.10),   # higher high
    (1.14, 1.09),
]


def bullish_candles():
    return candles_from_ranges(BULLISH, timeframe=Timeframe.H1)


def bearish_candles():
    return candles_from_ranges(BEARISH, timeframe=Timeframe.H1)


class TestSwingDetection:
    def test_finds_alternating_highs_and_lows(self):
        swings = find_swings(bullish_candles(), left=1, right=1)
        kinds = [s.kind for s in swings]
        assert SwingKind.HIGH in kinds
        assert SwingKind.LOW in kinds
        assert kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]

    def test_pivot_prices_match_the_ranges(self):
        swings = find_swings(bullish_candles(), left=1, right=1)
        highs = [s.price for s in swings if s.kind is SwingKind.HIGH]
        lows = [s.price for s in swings if s.kind is SwingKind.LOW]
        assert highs == [1.10, 1.13, 1.16]
        assert lows == [1.01, 1.045]

    def test_equal_adjacent_highs_create_no_pivot(self):
        candles = candles_from_ranges([(1.02, 1.00), (1.10, 1.05), (1.10, 1.05), (1.02, 1.00)])
        highs = [s for s in find_swings(candles, left=1, right=1) if s.kind is SwingKind.HIGH]
        assert highs == []

    def test_confirmation_index_is_delayed_by_right_bars(self):
        for swing in find_swings(bullish_candles(), left=1, right=2):
            assert swing.confirmed_at_index == swing.index + 2

    def test_not_enough_candles_returns_empty(self):
        assert find_swings(candles_from_ranges([(1.01, 0.99), (1.02, 1.00)]), left=2, right=2) == []

    def test_invalid_pivot_window_rejected(self):
        with pytest.raises(ValueError):
            find_swings(make_candles([1.0, 1.1, 1.2]), left=0, right=1)

    def test_stricter_pivot_window_returns_fewer_swings(self):
        loose = len(find_swings(bullish_candles(), left=1, right=1))
        strict = len(find_swings(bullish_candles(), left=2, right=2))
        assert strict <= loose


class TestLabels:
    def test_bullish_sequence_is_hh_hl(self):
        labels = [s.label for s in label_swings(find_swings(bullish_candles(), left=1, right=1))]
        assert SwingLabel.HIGHER_HIGH in labels
        assert SwingLabel.HIGHER_LOW in labels
        assert SwingLabel.LOWER_LOW not in labels
        assert SwingLabel.LOWER_HIGH not in labels

    def test_bearish_sequence_is_lh_ll(self):
        labels = [s.label for s in label_swings(find_swings(bearish_candles(), left=1, right=1))]
        assert SwingLabel.LOWER_HIGH in labels
        assert SwingLabel.LOWER_LOW in labels
        assert SwingLabel.HIGHER_HIGH not in labels
        assert SwingLabel.HIGHER_LOW not in labels

    def test_first_pivots_get_placeholder_labels(self):
        swings = label_swings(find_swings(bullish_candles(), left=1, right=1))
        assert swings[0].label is SwingLabel.FIRST_HIGH
        assert swings[1].label is SwingLabel.FIRST_LOW

    def test_equal_high_carries_the_previous_label(self):
        candles = candles_from_ranges(
            [(1.00, 0.98), (1.10, 1.02), (1.05, 0.99), (1.10, 1.03), (1.04, 1.00)]
        )
        swings = label_swings(find_swings(candles, left=1, right=1))
        highs = [s for s in swings if s.kind is SwingKind.HIGH]
        assert len(highs) == 2
        assert highs[1].price == highs[0].price
        assert highs[1].label is highs[0].label


class TestTrend:
    def test_bullish_structure(self):
        swings = label_swings(find_swings(bullish_candles(), left=1, right=1))
        trend, _ = classify_trend(swings)
        assert trend is StructuralTrend.BULLISH

    def test_bearish_structure(self):
        swings = label_swings(find_swings(bearish_candles(), left=1, right=1))
        trend, _ = classify_trend(swings)
        assert trend is StructuralTrend.BEARISH

    def test_range_when_highs_and_lows_disagree(self):
        swings = label_swings(
            find_swings(candles_from_ranges(RANGE_EXPANDING, timeframe=Timeframe.H1), left=1, right=1)
        )
        trend, notes = classify_trend(swings)
        assert trend is StructuralTrend.RANGE
        assert notes

    def test_undefined_without_enough_pivots(self):
        swings = label_swings(find_swings(candles_from_ranges([(1.01, 0.99), (1.02, 1.00), (1.03, 1.005)]), left=1, right=1))
        trend, notes = classify_trend(swings)
        assert trend is StructuralTrend.UNDEFINED
        assert notes


class TestAnalysis:
    def test_analysis_uses_closed_candles_only_by_default(self):
        candles = candles_from_ranges(BULLISH, timeframe=Timeframe.H1, closed_last=False)
        analysis = analyse_structure("EURUSD", "H1", candles, left=1, right=1)
        assert analysis.using_closed_candles_only is True
        assert analysis.bars_analyzed == len(candles) - 1
        assert all(s.index < len(candles) - 1 for s in analysis.swings)
        assert any("still-forming" in note for note in analysis.notes)

    def test_analysis_can_include_the_forming_candle_explicitly(self):
        candles = candles_from_ranges(BULLISH, timeframe=Timeframe.H1, closed_last=False)
        analysis = analyse_structure("EURUSD", "H1", candles, left=1, right=1, closed_only=False)
        assert analysis.bars_analyzed == len(candles)

    def test_analysis_reports_last_swings_and_labels(self):
        analysis = analyse_structure("EURUSD", "H1", bullish_candles(), left=1, right=1)
        assert analysis.trend is StructuralTrend.BULLISH
        assert analysis.last_swing_high.price == 1.16
        assert analysis.last_swing_low.price == 1.045
        assert [label.value for label in analysis.labels][:2] == ["H", "L"]

    def test_recent_labels_helper(self):
        analysis = analyse_structure("EURUSD", "H1", bullish_candles(), left=1, right=1)
        labels = recent_labels(analysis, 4)
        assert labels == ["HH", "HL", "HH"]

    def test_symbol_normalisation_and_unknown_symbol_note(self):
        analysis = analyse_structure("eur/usd", "H1", bullish_candles(), left=1, right=1)
        assert analysis.symbol == "EURUSD"
        unknown = analyse_structure("ZZZQQQ", "H1", bullish_candles(), left=1, right=1)
        assert any("not in the instrument catalog" in note for note in unknown.notes)

    def test_no_smc_claim_is_made(self):
        """Phase 1 must not report SMC/ICT structures."""
        payload = analyse_structure("EURUSD", "H1", bullish_candles(), left=1, right=1).model_dump_json()
        for forbidden in ("BOS", "CHOCH", "ORDER_BLOCK", "ORDER BLOCK", "FVG", "LIQUIDITY"):
            assert forbidden not in payload.upper()
