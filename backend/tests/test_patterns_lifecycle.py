"""Chartist engine - lifecycle, breakout, retest and deduplication.

The rule that matters most here: PATTERN DETECTED, BREAKOUT DETECTED and PATTERN
CONFIRMED are three separate events; a retest only exists after a confirmed
breakout; and one formation keeps one identity (`dedup_key`) for its whole life,
so the dashboard is never spammed with the same detection on every candle.
"""

from __future__ import annotations

import pytest

from app.schemas.market import CandleSeries
from tests.pattern_fixtures import BPL, build_series, double_top


def truncate(series: CandleSeries, bars: int) -> CandleSeries:
    return series.model_copy(update={"candles": series.candles[:bars]})


def event_types(events) -> list[str]:
    return [event.event_type for event in events]


def only(events, event_type: str):
    matches = [event for event in events if event.event_type == event_type]
    assert matches, f"{event_type} missing from {event_types(events)}"
    return matches[0]


class TestStatusLifecycle:
    def test_a_formation_starts_detected_and_unconfirmed(self, engine):
        series = double_top().series
        result = engine.analyse(series)
        detection = next(d for d in result.detections if d.pattern == "DOUBLE_TOP")
        assert detection.status.value == "DETECTED"
        assert detection.confirmation.confirmed is False
        assert detection.invalidation.invalidated is False
        events = engine.commit(result)
        assert event_types(events).count("PATTERN_DETECTED") >= 1
        assert "PATTERN_CONFIRMED" not in event_types(events)

    def test_breakout_confirms_the_formation_in_three_separate_events(self, engine):
        formation = double_top().series
        engine.analyse(formation)
        engine.commit(engine.analyse(formation))  # first run announces DETECTED

        engine.registry.clear()  # simulate a fresh process on the same formation
        full = double_top(breakout=True).series
        result = engine.analyse(full)
        events = engine.commit(result)
        assert set(["PATTERN_DETECTED", "BREAKOUT_DETECTED", "PATTERN_CONFIRMED"]).issubset(
            set(event_types(events))
        )
        detected = only(events, "PATTERN_DETECTED")
        breakout = only(events, "BREAKOUT_DETECTED")
        confirmed = only(events, "PATTERN_CONFIRMED")
        assert detected.detection.status.value in {"DETECTED", "CONFIRMED"}
        assert breakout.breakout is not None
        assert breakout.breakout.level > breakout.breakout.breakout_price  # bearish break, below the neckline

    def test_confirmation_requires_a_close_beyond_the_level(self, engine):
        """A wick through the neckline is not a breakout: closes decide."""
        series = build_series(
            [
                1.0960, 1.1000, 1.1040, 1.1100, 1.1075, 1.10995,
                1.1085,
                1.10738,  # wick pierces the neckline, the close sits exactly on it
                1.1095,
            ],
            bars_per_leg=BPL,
        )
        engine.params.breakout.buffer_pips = 1.0
        result = engine.analyse(series)
        detection = next((d for d in result.detections if d.pattern == "DOUBLE_TOP"), None)
        assert detection is not None
        assert detection.status.value == "DETECTED", "an intraday wick must not confirm the pattern"
        assert detection.breakout is None

    def test_the_breakout_event_carries_the_real_level_and_price(self, engine):
        full = double_top(breakout=True).series
        result = engine.analyse(full)
        events = engine.commit(result)
        breakout = only(events, "BREAKOUT_DETECTED").breakout
        assert breakout.level_type == "NECKLINE"
        assert breakout.level == pytest.approx(1.10738, abs=1e-5)
        assert breakout.breakout_price < breakout.level
        assert breakout.direction.value == "BEARISH"
        assert breakout.confirming_candle_time == breakout.breakout_time
        assert breakout.volume is None, "the Forex provider returns no volume: never invent it"

    def test_invalidation_when_price_closes_beyond_both_peaks(self, engine):
        formation = double_top().series
        engine.analyse(formation)
        engine.commit(engine.analyse(formation))
        result = engine.analyse(double_top(invalidation=True).series)
        events = engine.commit(result)
        detection = next(d for d in result.detections if d.pattern == "DOUBLE_TOP")
        assert detection.status.value == "INVALIDATED"
        assert detection.invalidation.invalidated is True
        assert detection.invalidation.invalidated_at is not None
        assert "PATTERN_INVALIDATED" in event_types(events)
        assert "PATTERN_CONFIRMED" not in event_types(events), (
            "a close above both peaks is the invalidation, never the confirmation"
        )

    def test_expiry_after_the_confirmation_window(self, engine):
        formation = double_top().series
        engine.analyse(formation)
        engine.commit(engine.analyse(formation))
        result = engine.analyse(double_top(expiring=True).series)
        events = engine.commit(result)
        detection = next(d for d in result.detections if d.pattern == "DOUBLE_TOP")
        assert detection.status.value == "EXPIRED"
        assert "PATTERN_EXPIRED" in event_types(events)

    def test_a_level_that_is_never_broken_is_never_retested(self, engine):
        """Price comes back to the neckline from above without breaking it."""
        series = build_series(
            [1.0960, 1.1000, 1.1040, 1.1100, 1.1075, 1.10995, 1.10740, 1.1090],
            bars_per_leg=BPL,
        )
        engine.commit(engine.analyse(series))
        result = engine.analyse(series)
        events = engine.commit(result)
        assert "RETEST_DETECTED" not in event_types(events)
        assert "BREAKOUT_DETECTED" not in event_types(events)

    def test_retest_only_after_a_confirmed_breakout(self, engine):
        engine.analyse(double_top().series)
        engine.commit(engine.analyse(double_top().series))
        result = engine.analyse(double_top(retest=True).series)
        events = engine.commit(result)
        assert event_types(events).index("PATTERN_CONFIRMED") < event_types(events).index("RETEST_DETECTED")
        retest = only(events, "RETEST_DETECTED").retest
        assert retest.breakout_level == pytest.approx(1.10738, abs=1e-5)
        assert retest.breakout_candle_time <= retest.retest_candle_time
        assert retest.distance_to_level_pips <= 3.0
        assert retest.confirmed in (True, False)
        assert retest.candles_after_breakout >= 1

    def test_a_tracked_formation_is_re_evaluated_on_new_bars(self, engine):
        """The formation is not re-derived after 60 bars, yet its breakout must fire."""
        formation = double_top().series
        engine.analyse(formation)
        engine.commit(engine.analyse(formation))
        series_full = double_top(breakout=True).series

        # the detector no longer sees the same pivots (window trimmed), so only the
        # tracked registry can confirm it
        trimmed = truncate(series_full, len(series_full.candles))
        trimmed = trimmed.model_copy(update={"candles": trimmed.candles[20:]})
        result = engine.analyse(trimmed)
        events = engine.commit(result)
        assert "PATTERN_CONFIRMED" in event_types(events), event_types(events)


def _fresh_engine(engine):
    from app.patterns.engine import ChartPatternEngine
    from app.patterns.params import PatternParams

    return ChartPatternEngine(PatternParams())


class TestDeduplication:
    def test_the_same_formation_keeps_one_id_across_runs(self, engine):
        series = double_top().series
        first = next(d for d in engine.analyse(series).detections if d.pattern == "DOUBLE_TOP")
        engine.commit(engine.analyse(series))
        second = next(d for d in engine.analyse(series).detections if d.pattern == "DOUBLE_TOP")
        assert first.id == second.id
        assert first.dedup_key == second.dedup_key
        assert first.dedup_key.startswith("ct_")

    def test_no_event_is_republished_for_an_unchanged_formation(self, engine):
        series = double_top().series
        engine.commit(engine.analyse(series))
        events = engine.commit(engine.analyse(series))
        assert events == [], "a stable formation must not re-emit PATTERN_DETECTED"

    def test_the_dedup_key_is_built_from_the_real_pivots(self, engine):
        series = double_top().series
        detection = next(d for d in engine.analyse(series).detections if d.pattern == "DOUBLE_TOP")
        assert detection.dedup_key.startswith("ct_") and len(detection.dedup_key) == 19
        pivots = detection.evidence_points["pivots"]
        times = [p["timestamp"] for p in pivots.values()]
        assert len(set(times)) == len(times), "a pivot can never appear twice in one formation"
        indexes = [p["index"] for p in pivots.values()]
        assert indexes == sorted(indexes)

    def test_a_new_formation_of_the_same_pair_gets_a_new_id(self, engine):
        first = next(d for d in engine.analyse(double_top().series).detections if d.pattern == "DOUBLE_TOP")
        engine.commit(engine.analyse(double_top().series))
        # a second, clearly different double top later in the series
        other = build_series(
            [1.0900, 1.1000, 1.1100, 1.1075, 1.10995, 1.1085, 1.1000, 1.0900],
            bars_per_leg=BPL,
        )
        second = next(d for d in engine.analyse(other).detections if d.pattern == "DOUBLE_TOP")
        assert second.dedup_key != first.dedup_key

    def test_breakout_does_not_change_the_identity(self, engine):
        formation = double_top().series
        engine.commit(engine.analyse(formation))
        before = next(d for d in engine.registry.values() if d.pattern == "DOUBLE_TOP")
        result = engine.analyse(double_top(breakout=True).series)
        engine.commit(result)
        after = next(d for d in result.detections if d.pattern == "DOUBLE_TOP")
        assert after.id == before.id
