"""Phase 3 - structural events, chartist reuse, level context and confluence.

Three ideas are tested here and nowhere else:

* structure events (IMPULSION, CONSOLIDATION) are **measured states**, not guesses;
* REJECTION and FAILED_BREAKOUT consume the **real levels and breakouts of the
  chartist engine (Phase 2)** - this engine never recomputes a level or a breakout;
* level context and confluence are **informative**: they change the wording and the
  drawing, never the confidence and never a trading decision.
"""

from __future__ import annotations

import pytest

from app.price_action.engine import PriceActionEngine
from app.price_action.params import PriceActionParams
from tests import price_action_fixtures as fx


@pytest.fixture
def engine():
    return PriceActionEngine(PriceActionParams())


def patterns(dets) -> list[str]:
    return [d.pattern for d in dets]


def one(dets, pattern):
    found = [d for d in dets if d.pattern == pattern]
    assert found, f"expected {pattern}, got {patterns(dets)}"
    return found[0]


def extend(series, *bars):
    extra = [bar.build(len(series.candles) + offset) for offset, bar in enumerate(bars)]
    return series.model_copy(update={"candles": series.candles + extra})


class TestImpulsion:
    def test_positive_measures_the_move(self, engine):
        detection = one(engine.analyse(fx.impulsion()).detections, "IMPULSION")
        measurements = detection.evidence_points["measurements"]
        assert detection.direction.value == "BULLISH"
        assert measurements["bars"] == 6
        assert measurements["net_move_pips"] == pytest.approx(24.0, abs=0.5)
        assert measurements["efficiency"] >= 0.8
        assert measurements["required_pips"] >= 15.0
        assert measurements["max_pullback_ratio"] <= 0.4
        assert detection.status.value == "DETECTED"

    def test_negative_when_the_run_is_too_short(self, engine):
        """Three aligned bars is below impulse_min_bars (4): no state."""
        assert "IMPULSION" not in patterns(engine.analyse(fx.impulsion(bars=3)).detections)

    def test_boundary_minimum_bars_accepted(self, engine):
        """Exactly 4 aligned bars: accepted (the rule is >= 4)."""
        detection = one(engine.analyse(fx.impulsion(bars=4)).detections, "IMPULSION")
        assert detection.evidence_points["measurements"]["bars"] == 4

    def test_negative_when_the_move_is_too_small(self, engine):
        """Six bars but only 6 pips in total: under the 15-pip floor."""
        assert "IMPULSION" not in patterns(engine.analyse(fx.impulsion(step=1.0)).detections)

    def test_boundary_move_exactly_at_the_floor(self, engine):
        """Net move exactly at the floor (15 pips over 5 bars of 3 pips)."""
        detection = one(engine.analyse(fx.impulsion(bars=5, step=3.0)).detections, "IMPULSION")
        assert detection.evidence_points["measurements"]["net_move_pips"] == pytest.approx(15.0, abs=0.2)

    def test_negative_on_a_choppy_move(self, engine):
        """Same net move but with a deep pullback inside: anti-chop rule rejects it."""
        run = [
            fx.BarSpec(open=0.0, high=8.4, low=-0.2, close=8.0),
            fx.BarSpec(open=8.0, high=10.2, low=2.0, close=2.5),   # closes back down
            fx.BarSpec(open=2.5, high=10.2, low=2.2, close=10.0),
            fx.BarSpec(open=10.0, high=18.4, low=9.8, close=18.0),
            fx.BarSpec(open=18.0, high=21.4, low=17.8, close=21.0),
        ]
        series = fx.with_calm(*run, calm=70)
        dets = engine.analyse(series).detections
        assert "IMPULSION" not in patterns(dets)

    def test_state_is_refreshed_never_duplicated(self, engine):
        """Two runs on the same series: one identity, one single event."""
        series = fx.impulsion()
        first = engine.analyse(series)
        first_events = engine.commit(first)
        second = engine.analyse(series)
        second_events = engine.commit(second)
        assert [e.event_type for e in first_events] == ["PRICE_ACTION_DETECTED"]
        assert second_events == []
        assert one(first.detections, "IMPULSION").id == one(second.detections, "IMPULSION").id

    def test_state_ends_when_the_run_ends(self, engine):
        series = fx.impulsion()
        engine.commit(engine.analyse(series))
        broken = extend(series, fx.BarSpec(open=24.0, high=24.4, low=20.0, close=20.5))
        events = engine.commit(engine.analyse(broken))
        kinds = {e.event_type for e in events}
        assert "PRICE_ACTION_EXPIRED" in kinds
        expired = [e for e in events if e.event_type == "PRICE_ACTION_EXPIRED"]
        assert expired[0].detection.pattern == "IMPULSION"


class TestConsolidation:
    def test_positive_measures_the_compression(self, engine):
        detection = one(engine.analyse(fx.consolidation()).detections, "CONSOLIDATION")
        measurements = detection.evidence_points["measurements"]
        assert measurements["compression"] <= 0.6
        assert measurements["box_height_pips"] <= measurements["max_height_pips"]
        assert measurements["containment_bars"] >= 5
        assert detection.direction.value == "NEUTRAL"
        assert detection.status.value == "DETECTED"

    def test_negative_without_compression(self, engine):
        """Reference and box have the same mean range: nothing is compressed."""
        boxes = []
        price = 0.0
        for _ in range(50):
            boxes.append(fx.BarSpec(open=price, high=price + 6.0, low=price, close=price + 5.0))
            price += 0.5
        series = fx.series(fx.calm_bars(30) + boxes)
        assert "CONSOLIDATION" not in patterns(engine.analyse(series).detections)

    def test_negative_when_the_box_is_too_high(self, engine):
        """Compression is respected but the box is 40 pips tall."""
        box = [
            fx.BarSpec(open=0.0, high=40.0, low=0.0, close=2.0),
            fx.BarSpec(open=2.0, high=4.0, low=0.5, close=3.0),
            fx.BarSpec(open=3.0, high=5.0, low=0.2, close=4.0),
            fx.BarSpec(open=4.0, high=6.0, low=0.4, close=5.0),
            fx.BarSpec(open=5.0, high=7.0, low=0.6, close=6.0),
            fx.BarSpec(open=6.0, high=8.0, low=0.8, close=7.0),
        ]
        assert "CONSOLIDATION" not in patterns(engine.analyse(fx.consolidation(box_bars=6, box_range=4.0)).detections)
        series = fx.consolidation(box_bars=6, box_range=4.0)
        series = series.model_copy(update={"candles": series.candles[:-6] + [bar.build(len(series.candles) - 6 + i) for i, bar in enumerate(box)]})
        assert "CONSOLIDATION" not in patterns(engine.analyse(series).detections)

    def test_identity_is_stable_while_the_box_holds(self, engine):
        series = fx.consolidation()
        first = engine.commit(engine.analyse(series))
        assert [e.event_type for e in first] == ["PRICE_ACTION_DETECTED"]
        inside = fx.BarSpec(open=0.5, high=3.5, low=0.2, close=3.0)
        extended = extend(series, inside)
        second = engine.commit(engine.analyse(extended))
        assert second == [], "a box that still holds is refreshed, never re-emitted"

    def test_state_ends_when_price_leaves_the_box(self, engine):
        series = fx.consolidation()
        engine.commit(engine.analyse(series))
        breakout = fx.BarSpec(open=1.0, high=30.0, low=0.8, close=28.0)
        events = engine.commit(engine.analyse(extend(series, breakout)))
        expired = [e for e in events if e.event_type == "PRICE_ACTION_EXPIRED"]
        assert expired and expired[0].detection.pattern == "CONSOLIDATION"


class TestRejection:
    def test_positive_on_a_real_support(self, engine):
        series = fx.rejection()
        level = fx.chartist_level("SUPPORT", 0.0, time=series.candles[-1].time)
        detection = one(engine.analyse(series, chartist=[level]).detections, "REJECTION")
        measurements = detection.evidence_points["measurements"]
        assert measurements["level_kind"] == "SUPPORT"
        assert measurements["distance_to_level_pips"] <= measurements["tolerance_pips"]
        assert measurements["close_distance_pips"] >= 3.0
        assert measurements["rejection_wick_ratio"] >= 0.5
        assert detection.direction.value == "BULLISH"
        assert "SUPPORT" in detection.evidence[0]

    def test_no_level_no_rejection(self, engine):
        """A wick into empty space is not a rejection - and is never reported as one."""
        series = fx.rejection()
        assert "REJECTION" not in patterns(engine.analyse(series).detections)

    def test_level_far_away_is_not_touched(self, engine):
        series = fx.rejection()
        level = fx.chartist_level("SUPPORT", -9.0, time=series.candles[-1].time)  # 8 pips below the wick
        assert "REJECTION" not in patterns(engine.analyse(series, chartist=[level]).detections)

    def test_close_must_move_away(self, engine):
        """Wick on the level but the close stays on it: no rejection."""
        series = fx.rejection(close_above=0.5)
        level = fx.chartist_level("SUPPORT", 0.0, time=series.candles[-1].time)
        assert "REJECTION" not in patterns(engine.analyse(series, chartist=[level]).detections)

    def test_old_level_is_ignored(self, engine):
        """A level older than max_level_age_bars is not part of the current context."""
        series = fx.rejection()
        stale = fx.chartist_level("SUPPORT", 0.0, time=series.candles[0].time)  # age = 70 bars
        params = PriceActionParams()
        params.levels.max_level_age_bars = 20
        assert "REJECTION" not in patterns(
            PriceActionEngine(params).analyse(series, chartist=[stale]).detections
        )
        # with the default window (80 bars) the very same level is still valid
        assert "REJECTION" in patterns(engine.analyse(series, chartist=[stale]).detections)

    def test_resistance_rejects_from_above(self, engine):
        bar = fx.BarSpec(open=2.0, high=6.0, low=1.6, close=1.0)  # wick above, close below
        series = fx.with_calm(bar, calm=70)
        level = fx.chartist_level("RESISTANCE", 5.0, time=series.candles[-1].time)
        detection = one(engine.analyse(series, chartist=[level]).detections, "REJECTION")
        assert detection.direction.value == "BEARISH"
        assert detection.evidence_points["measurements"]["side"] == "ABOVE"

    def test_tolerance_comes_from_the_parameters(self, engine):
        """The same 3-pip gap is refused by default and accepted with a wider tolerance."""
        bar = fx.BarSpec(open=2.0, high=3.0, low=-3.0, close=4.0)
        series = fx.with_calm(bar, calm=70)
        level = fx.chartist_level("SUPPORT", 0.0, time=series.candles[-1].time)
        assert "REJECTION" not in patterns(engine.analyse(series, chartist=[level]).detections)
        params = PriceActionParams()
        params.structure.rejection_level_tolerance_pips = 6.0
        dets = PriceActionEngine(params).analyse(series, chartist=[level]).detections
        assert "REJECTION" in patterns(dets)
        # 6 pips is the requested tolerance, and the measured distance is reported
        assert one(dets, "REJECTION").evidence_points["measurements"]["tolerance_pips"] >= 6.0


class TestFailedBreakout:
    def _series(self):
        calm = fx.calm_bars(70)
        up = fx.BarSpec(open=0.0, high=3.4, low=-0.2, close=3.0)     # breaks above 0.0
        back = fx.BarSpec(open=3.0, high=3.2, low=-3.0, close=-2.5)  # closes 2.5 pips back inside
        return fx.series(calm + [up, back])

    def _chartist(self, series, *, direction="BULLISH", level_pips=0.0):
        return [
            fx.chartist_breakout(
                level_pips=level_pips,
                breakout_time=series.candles[70].time,
                direction=direction,
                breakout_price_pips=3.0,
            )
        ]

    def test_positive(self, engine):
        series = self._series()
        detection = one(engine.analyse(series, chartist=self._chartist(series)).detections, "FAILED_BREAKOUT")
        points = detection.evidence_points
        assert points["breakout_level"] == pytest.approx(fx.px(0.0), abs=1e-9)
        assert points["breakout_candle"] == series.candles[70].time
        assert points["failure_candle"] == series.candles[71].time
        assert points["return_price"] < points["breakout_level"]
        assert detection.direction.value == "BEARISH"
        assert points["measurements"]["bars_after_breakout"] == 1

    def test_distinct_event_is_published(self, engine):
        """FAILED_BREAKOUT is its own event, next to the lifecycle one."""
        series = self._series()
        result = engine.analyse(series, chartist=self._chartist(series))
        events = engine.commit(result)
        kinds = [e.event_type for e in events]
        assert "FAILED_BREAKOUT" in kinds
        # the dedicated event immediately follows the detection it describes
        index = kinds.index("FAILED_BREAKOUT")
        assert kinds[index - 1] == "PRICE_ACTION_DETECTED"
        assert events[index].detection.pattern == "FAILED_BREAKOUT"
        extra = events[index].extra["failure"]
        assert extra["breakout_level"] == pytest.approx(fx.px(0.0), abs=1e-9)
        assert extra["failure_candle"] == series.candles[71].time
        assert extra["direction"] == "BEARISH"

    def test_no_failure_if_price_holds(self, engine):
        calm = fx.calm_bars(70)
        up = fx.BarSpec(open=0.0, high=3.4, low=-0.2, close=3.0)
        hold = fx.BarSpec(open=3.0, high=5.0, low=2.5, close=4.0)  # stays above the level
        series = fx.series(calm + [up, hold])
        chartist = self._chartist(series)
        assert "FAILED_BREAKOUT" not in patterns(engine.analyse(series, chartist=chartist).detections)

    def test_tolerance_of_the_return(self, engine):
        """A 0.5-pip return is under the 1-pip rule: not a failed breakout."""
        calm = fx.calm_bars(70)
        up = fx.BarSpec(open=0.0, high=3.4, low=-0.2, close=3.0)
        graze = fx.BarSpec(open=3.0, high=3.2, low=-0.5, close=-0.5)
        series = fx.series(calm + [up, graze])
        assert "FAILED_BREAKOUT" not in patterns(engine.analyse(series, chartist=self._chartist(series)).detections)

    def test_mirrored_case(self, engine):
        calm = fx.calm_bars(70)
        down = fx.BarSpec(open=0.0, high=0.2, low=-3.4, close=-3.0)
        back = fx.BarSpec(open=-3.0, high=3.5, low=-3.2, close=2.5)
        series = fx.series(calm + [down, back])
        chartist = self._chartist(series, direction="BEARISH")
        detection = one(engine.analyse(series, chartist=chartist).detections, "FAILED_BREAKOUT")
        assert detection.direction.value == "BULLISH"
        assert detection.evidence_points["return_price"] > detection.evidence_points["breakout_level"]

    def test_no_breakout_no_failure(self, engine):
        series = self._series()
        assert "FAILED_BREAKOUT" not in patterns(engine.analyse(series).detections)

    def test_engine_never_recomputes_a_breakout(self, engine):
        """Without the chartist reference the engine reports nothing, even though
        price objectively broke and returned: the breakout belongs to Phase 2."""
        series = self._series()
        # the candles alone contain the break and the return...
        assert series.candles[70].close > series.candles[71].close
        # ...but with no breakout reference, the price-action engine stays silent
        assert "FAILED_BREAKOUT" not in patterns(engine.analyse(series).detections)


class TestLevelContextAndConfluence:
    def test_context_label_uses_the_real_level(self, engine):
        series = fx.bullish_engulfing()
        low = series.candles[-1].low
        level = fx.chartist_level("SUPPORT", (low - fx.BASE) / fx.PIP - 1.0, time=series.candles[-1].time)
        detection = one(engine.analyse(series, chartist=[level]).detections, "BULLISH_ENGULFING")
        context = detection.evidence_points["level_context"]
        assert context["label"] == "BULLISH_ENGULFING_AT_SUPPORT"
        assert context["nearest"]["kind"] == "SUPPORT"
        assert any("CONTEXTE" in note for note in detection.notes)

    def test_context_never_changes_the_confidence(self, engine):
        """An isolated pattern and the same pattern on a support carry the same score:
        the context is informative, it is not a bonus."""
        series = fx.bullish_engulfing()
        low = series.candles[-1].low
        level = fx.chartist_level("SUPPORT", (low - fx.BASE) / fx.PIP - 1.0, time=series.candles[-1].time)
        alone = one(engine.analyse(series).detections, "BULLISH_ENGULFING")
        with_context = one(engine.analyse(series, chartist=[level]).detections, "BULLISH_ENGULFING")
        assert alone.confidence == with_context.confidence
        assert [f.criterion for f in alone.confidence_factors] == [
            f.criterion for f in with_context.confidence_factors
        ]
        # and the context criteria are explicitly flagged as not counted
        for criterion in with_context.evidence_points["context_criteria"]:
            assert criterion["counts_towards_confidence"] is False

    def test_no_invented_context_without_layout(self, engine):
        detection = one(engine.analyse(fx.bullish_engulfing()).detections, "BULLISH_ENGULFING")
        context = detection.evidence_points["level_context"]
        assert context["label"] is None
        assert context["relations"] == []
        assert context["trading_signal"] is False

    def test_confluence_groups_three_engines_without_score(self, engine):
        series = fx.consolidation()
        engine.commit(engine.analyse(series))
        chartist = [fx.chartist_level("SUPPORT", 0.0, time=series.candles[-1].time)]
        groups = engine.confluence_groups(chartist=chartist)
        assert groups, "the confluence view must group the current state"
        payload = groups[0].as_dict()
        assert set(payload["groups"]) == {"chartist", "price_action", "structure"}
        assert payload["trading_signal"] is False
        assert "aucun signal" in payload["note"].lower() or "aucune recommandation" in payload["note"].lower()
        assert not any(key in payload for key in ("score", "strength", "signal", "entry"))

    def test_unknown_symbol_filter(self, engine):
        engine.commit(engine.analyse(fx.bullish_engulfing()))
        assert engine.confluence_groups(symbol="EURUSD") != []
        assert engine.confluence_groups(symbol="USDJPY") == []


class TestStructureNegativeControl:
    """§20 - the engine must not massively invent structure on noise."""

    @pytest.mark.parametrize("seed", [3, 11, 29, 47, 101])
    def test_no_state_on_structureless_noise(self, engine, seed):
        series = fx.noise_series(seed=seed, amplitude=3.0, bars=300)
        dets = engine.analyse(series).detections
        structure = [d for d in dets if d.pattern in {"IMPULSION", "CONSOLIDATION"}]
        assert structure == [], f"structure invented on noise: {[d.pattern for d in structure]}"

    @pytest.mark.parametrize("seed", [11, 29])
    def test_detection_volume_stays_low_on_noise(self, engine, seed):
        """Measured honestly: a few candlestick shapes exist in a 300-bar walk (they
        are real geometry), but never anything close to a detection per bar."""
        series = fx.noise_series(seed=seed, amplitude=3.0, bars=300)
        dets = engine.analyse(series).detections
        assert len(dets) <= 10, f"{len(dets)} detections on 300 noise bars"
        # and each of them is tied to a real, distinct candle
        candles = [c.time for c in series.candles]
        assert len({d.detected_at_bar_time for d in dets}) == len(dets)
        assert all(d.detected_at_bar_time in candles for d in dets)
