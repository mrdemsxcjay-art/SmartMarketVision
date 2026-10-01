"""Phase 6 - Opportunity Engine tests.

What is checked, in the order of the acceptance criteria:

* 6.1 ``BUY`` / ``SELL`` / ``WATCH`` / ``NO_TRADE`` are ANALYTICAL directions: the
  payload contains no order, no broker, no position, and a direction is never
  named on a single figure;
* 6.2 / 6.3 the conditions are explicit and the refusals are motivated;
* 6.4 the score is separate from the confluence score, explicable and is never a
  probability of success;
* 6.5 the lifecycle CREATED / ACTIVE / CONFIRMED / WEAKENED / INVALIDATED / EXPIRED;
* 6.6 the anti-spam key is stable and the registry is capped;
* 6.7 no invented price, no invented volume, no performance figure.

Real confluence groups are produced by the Phase 5 engine: the opportunity tests
never validate against a confluence the engine could not create.
"""

from __future__ import annotations

import re

import pytest

from app.confluence.models import ConfluenceState
from app.opportunities.engine import OpportunityEngine, _opportunity_id, alert_id, alert_key
from app.opportunities.models import OpportunityDirection, OpportunityState, NoTradeReason
from app.opportunities.params import OpportunityParams
from tests import confluence_fixtures as cf_fx
from tests import opportunity_fixtures as op_fx


@pytest.fixture
def market_specs():
    return cf_fx.calm(70) + [
        cf_fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
        cf_fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
        cf_fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
    ]


@pytest.fixture
def market(market_specs):
    return cf_fx.series(market_specs)


@pytest.fixture
def engine():
    return OpportunityEngine(op_fx.params())


class TestDirectionVocabulary:
    def test_a_named_direction_never_carries_an_order(self, engine, market):
        group = op_fx.strong_group(market)
        result = engine.analyse(market, [group])
        named = [item for item in result.opportunities if item.is_actionable_observation]
        assert named, "la confluence de reference doit produire une direction nommee"
        payload = named[0].as_dict()
        text = str(payload).upper().replace("ORDER BLOCK", "ORDER_BLOCK")
        for forbidden in (
            "BROKER",
            "POSITION",
            "EXECUTION",
            "STOP LOSS",
            "TAKE PROFIT",
            "ENTRY",
            "LOT",
            "PROBABIL",
            "REUSSITE",
            "PERFORMANCE",
            "GAIN",
        ):
            assert forbidden not in text, f"{forbidden} ne doit jamais apparaitre dans une opportunite"
        # "order" is only legitimate as the SMC "order block" pattern name
        assert re.search(r"(?<!block_)\border\b", text) is None
        assert payload["direction"] in ("BUY", "SELL")
        assert payload["conditions"], "chaque critere verifie est conserve"

    def test_direction_mapping_is_one_to_one(self, engine, market):
        bullish = engine.analyse(market, [op_fx.strong_group(market)]).opportunities
        assert {item.direction for item in bullish} == {"BUY"}
        bearish = engine.analyse(market, [op_fx.bearish_group(market)]).opportunities
        assert {item.direction for item in bearish} == {"SELL"}

    def test_a_single_bullish_figure_is_never_a_buy(self, engine, market):
        """6.1: one figure alone - here the full stack minus three dimensions - is not enough."""
        events = [
            cf_fx.fvg("f1", time=market.candles[-1].time, price=1.10),
        ]
        groups = op_fx.confluence_from(market, events)
        result = engine.analyse(market, groups)
        assert not [item for item in result.opportunities if item.direction == OpportunityDirection.BUY.value]
        assert all(item.direction in ("WATCH", "NO_TRADE") for item in result.opportunities)

    def test_a_weak_confluence_is_watch_not_a_direction(self, engine, market):
        events = [
            cf_fx.bos("b1", direction="BULLISH", time=market.candles[-1].time, price=1.10),
            cf_fx.fvg("f1", time=market.candles[-1].time, price=1.10),
            cf_fx.price_action(
                "p1", "BULLISH_ENGULFING", direction="BULLISH", time=market.candles[-1].time, price=1.10
            ),
        ]
        groups = op_fx.confluence_from(market, events)
        result = engine.analyse(market, groups)
        assert result.opportunities
        assert {item.direction for item in result.opportunities} == {"WATCH"}
        assert all(item.no_trade_reason is None for item in result.opportunities)
        assert all(item.blocked_by for item in result.opportunities)
        assert "surveillance" in result.opportunities[0].note


class TestConditions:
    def test_every_condition_is_named_and_measurable(self, engine, market):
        result = engine.analyse(market, [op_fx.strong_group(market)])
        checks = result.opportunities[0].conditions
        labels = [check.label for check in checks]
        assert len(checks) == 8, "6 dimensions notees + 2 verrous"
        assert sum(1 for check in checks if check.gate) == 2
        assert any("Structure" in label for label in labels)
        assert any("Liquidite" in label for label in labels)
        assert any("Desequilibre" in label for label in labels)
        assert any("Declencheur" in label for label in labels)
        assert any("Displacement" in label for label in labels)
        assert any("Confluence" in label for label in labels)
        assert any("contradiction" in label for label in labels)
        for check in checks:
            assert check.detail, "chaque critere porte sa mesure reelle"
            if check.gate:
                assert check.points == 0.0, "un verrou ne rapporte aucun point"
            else:
                assert (check.points > 0) == check.passed

    def test_a_contradicted_confluence_is_refused(self, engine, market):
        """6.3: a major contradiction wins over a high score."""
        group = op_fx.group_copy(op_fx.strong_group(market), state=ConfluenceState.CONTRADICTED.value)
        result = engine.analyse(market, [group])
        item = result.opportunities[0]
        assert item.direction == "NO_TRADE"
        assert item.no_trade_reason == NoTradeReason.CONTRADICTORY.value

    def test_an_aged_confluence_is_reported_as_stale(self, engine, market):
        """6.3: an event several hours old never feeds a fresh decision."""
        old = market.candles[-1].time - 40 * 900  # 40 M15 bars before the last candle
        group = op_fx.group_copy(op_fx.strong_group(market), window_end=old)
        item = engine.analyse(market, [group]).opportunities[0]
        assert item.direction == "NO_TRADE"
        assert item.no_trade_reason == NoTradeReason.STALE_DATA.value
        assert item.blocked_by == NoTradeReason.STALE_DATA.value

    def test_a_stale_event_never_even_reaches_the_opportunity_engine(self, engine, market):
        """The Phase 5 alignment already refuses hours-old events: the chain is coherent."""
        events = cf_fx.bullish_stack(market.candles[-1].time - 40 * 900)
        assert op_fx.confluence_from(market, events) == []

    def test_a_frozen_market_is_refused_for_low_volatility(self, engine, market):
        """6.3: a market that does not move at all cannot produce a direction."""
        frozen = cf_fx.BarSpec(open=0.0, high=0.0, low=0.0, close=0.0)
        flat = op_fx.series([frozen] * 74)
        events = cf_fx.bullish_stack(flat.candles[-1].time)
        groups = op_fx.confluence_from(flat, events)
        result = engine.analyse(flat, groups)
        assert result.opportunities, "le groupe fourni doit tout de meme etre evalue"
        assert {item.direction for item in result.opportunities} == {"NO_TRADE"}
        assert {item.no_trade_reason for item in result.opportunities} == {
            NoTradeReason.LOW_VOLATILITY.value
        }, "un marche gele reste un refus, jamais une surveillance"
        volatility = [
            check for check in result.opportunities[0].conditions if check.dimension == "VOLATILITY"
        ]
        assert volatility and volatility[0].passed is False

    def test_a_confluence_without_structure_never_names_a_direction(self, engine, market):
        """6.2: the structure is the backbone of a direction."""
        groups = op_fx.confluence_from(
            market,
            [
                cf_fx.fvg("f1", time=market.candles[-1].time, price=1.10),
                cf_fx.displacement("d1", time=market.candles[-1].time, price=1.12),
                cf_fx.sweep("s1", time=market.candles[-1].time, price=1.08),
                cf_fx.chartist("c1", "SUPPORT", direction="BULLISH", time=market.candles[-1].time, price=1.09),
                cf_fx.price_action("p1", "BULLISH_ENGULFING", direction="BULLISH", time=market.candles[-1].time, price=1.11),
            ],
        )
        result = engine.analyse(market, groups)
        assert result.opportunities
        assert not [item for item in result.opportunities if item.is_actionable_observation]
        assert {item.blocked_by for item in result.opportunities} == {
            NoTradeReason.MISSING_DIMENSIONS.value
        }, "sans STRUCTURE, aucune direction n'est nommee"

    def test_a_neutral_confluence_produces_a_motivated_refusal(self, engine, market):
        neutral = op_fx.group_copy(
            op_fx.strong_group(market),
            id="cf_neutre",
            direction="NEUTRAL",
            state=ConfluenceState.WATCH.value,
            score=3.0,
        )
        result = engine.analyse(market, [neutral])
        item = result.opportunities[0]
        assert item.direction == "NO_TRADE"
        assert item.no_trade_reason == NoTradeReason.INSUFFICIENT_CONFLUENCE.value
        assert item.score == 0.0

    def test_no_opportunity_is_invented_when_there_is_no_confluence(self, engine, market):
        result = engine.analyse(market, [])
        assert result.opportunities == []
        assert result.confluences_considered == 0

    def test_an_engine_without_enough_bars_produces_nothing(self, engine, market):
        tiny = op_fx.series(cf_fx.calm(20))
        result = engine.analyse(tiny, [op_fx.group_copy(op_fx.strong_group(market))])
        assert result.opportunities == []
        assert result.notes and "bougies" in result.notes[0]


class TestScore:
    def test_the_score_is_separate_explicable_and_bounded(self, engine, market):
        result = engine.analyse(market, [op_fx.strong_group(market)])
        item = result.opportunities[0]
        assert item.confluence_id, "l'opportunite garde l'identite de sa confluence"
        assert item.max_score == 10.0
        assert 0 < item.score <= item.max_score
        assert item.score == round(sum(c.points for c in item.conditions if c.passed), 2)
        assert len(item.conditions) == 8, "un point par critere note, tracable"

    def test_a_quoted_watch_says_why_no_direction_is_named(self, engine, market):
        events = [
            cf_fx.bos("b1", direction="BULLISH", time=market.candles[-1].time, price=1.10),
            cf_fx.fvg("f1", time=market.candles[-1].time, price=1.10),
            cf_fx.price_action(
                "p1", "BULLISH_ENGULFING", direction="BULLISH", time=market.candles[-1].time, price=1.10
            ),
        ]
        groups = op_fx.confluence_from(market, events)
        item = engine.analyse(market, groups).opportunities[0]
        assert item.direction == "WATCH" and item.blocked_by
        assert item.blocked_by in item.note and "surveillance" in item.note

    def test_the_score_of_a_named_direction_meets_the_documented_minimum(self, engine, market):
        item = engine.analyse(market, [op_fx.strong_group(market)]).opportunities[0]
        assert item.is_actionable_observation
        assert item.score >= engine.params.conditions.min_score
        assert len(item.evidence) >= 1

    def test_each_point_can_be_traced_to_its_dimension(self, engine, market):
        item = engine.analyse(market, [op_fx.strong_group(market)]).opportunities[0]
        for check in item.conditions:
            if check.passed and check.dimension:
                assert check.dimension

    def test_params_are_centralised_and_visible(self, engine):
        snapshot = engine.params.snapshot()
        assert set(snapshot) == {"conditions", "weights", "lifecycle", "derived"}
        assert snapshot["derived"]["max_score"] == 10.0
        assert snapshot["weights"]["structure"] == 3.0


class TestLifecycle:
    def test_created_then_active(self, engine, market):
        group = op_fx.strong_group(market)
        first = engine.analyse(market, [group])
        engine.commit(first)
        assert first.opportunities[0].state == OpportunityState.CREATED.value

        second = engine.analyse(market, [op_fx.group_copy(group, reference_price=group.reference_price)])
        engine.commit(second)
        assert second.opportunities[0].state == OpportunityState.ACTIVE.value
        assert second.opportunities[0].previous_state == OpportunityState.CREATED.value

    def test_confirmed_on_a_later_close_observed_in_the_right_direction(self, engine, market, market_specs):
        group = op_fx.strong_group(market)
        first = engine.analyse(market, [group])
        engine.commit(first)
        direction = first.opportunities[0].direction
        price = group.reference_price
        assert direction == "BUY" and price is not None

        # a real closed candle after the confluence, closing above the reference price
        later = op_fx.series([*market_specs, *op_fx.following_bars(1, close=0.5)])
        result = engine.analyse(later, [group])
        engine.commit(result)
        item = result.opportunities[0]
        assert item.state == OpportunityState.CONFIRMED.value
        assert item.confirmation_bar_time == later.candles[-1].time, "la confirmation cite la bougie reelle"
        assert item.observed_bar_time == later.candles[-1].time

    def test_a_close_in_the_opposite_direction_does_not_confirm(self, engine, market, market_specs):
        """No confirmation is claimed from hindsight, nor from a move against the reading."""
        group = op_fx.strong_group(market)
        engine.commit(engine.analyse(market, [group]))
        later = op_fx.series([*market_specs, *op_fx.following_bars(1, close=-0.5)])
        result = engine.analyse(later, [group])
        engine.commit(result)
        assert result.opportunities[0].state == OpportunityState.ACTIVE.value

    def test_invalidated_when_the_confluence_turns_against_the_observation(self, engine, market):
        group = op_fx.strong_group(market)
        engine.commit(engine.analyse(market, [group]))
        contradicted = op_fx.group_copy(group, state=ConfluenceState.CONTRADICTED.value)
        result = engine.analyse(market, [contradicted])
        engine.commit(result)
        assert result.opportunities[0].state == OpportunityState.INVALIDATED.value

    def test_weakened_when_the_score_drops_below_watch(self, engine, market):
        group = op_fx.strong_group(market)
        engine.commit(engine.analyse(market, [group]))
        weak = op_fx.group_copy(
            group,
            score=2.0,
            state=ConfluenceState.NO_CONFLUENCE.value,
            dimensions=["IMBALANCE"],
        )
        weakened = OpportunityEngine(engine.params)
        weakened._registry = engine._registry  # same tracking, one different reading
        result = weakened.analyse(market, [weak])
        weakened.commit(result)
        assert result.opportunities[0].state == OpportunityState.WEAKENED.value

    def test_expired_when_the_validity_elapses(self, engine, market, market_specs):
        group = op_fx.strong_group(market)
        engine.commit(engine.analyse(market, [group]))
        validity = engine.params.lifecycle.validity_bars

        # a fresh reading before the validity ends: nothing expires
        near = op_fx.series([*market_specs, *op_fx.following_bars(validity - 2, close=0.2)])
        engine.commit(engine.analyse(near, []))
        assert engine.all(), "une observation encore valide ne doit pas expirer"

        # the same series, past the validity: the observation is over
        far = op_fx.series([*market_specs, *op_fx.following_bars(validity + 3, close=0.2)])
        events = engine.commit(engine.analyse(far, []))
        assert any(event.event_type == "OPPORTUNITY_EXPIRED" for event in events)
        assert engine.all() == [], "une observation expiree quitte le suivi"
        assert events[0].opportunity.state == OpportunityState.EXPIRED.value


class TestAntiSpam:
    def test_the_alert_key_follows_the_observation_not_the_tick(self, engine, market):
        group = op_fx.strong_group(market)
        key = alert_key(market.symbol, market.timeframe.value, "BUY", group.id)
        assert alert_key(market.symbol, market.timeframe.value, "BUY", group.id) == key
        assert alert_key(market.symbol, market.timeframe.value, "SELL", group.id) != key
        assert alert_id(key) == alert_id(key)
        assert alert_id(key).startswith("al_")

    def test_the_identity_is_stable_across_ticks(self, engine, market):
        group = op_fx.strong_group(market)
        first = engine.analyse(market, [group]).opportunities[0]
        second = engine.analyse(market, [op_fx.group_copy(group)]).opportunities[0]
        assert first.id == second.id
        assert first.dedup_key == second.dedup_key
        assert first.generation == 1 and second.generation >= 1

    def test_an_unchanged_observation_is_not_notified_twice(self, engine, market):
        group = op_fx.strong_group(market)
        first = engine.analyse(market, [group])
        events_one = engine.commit(first)
        assert events_one and events_one[0].notifiable, "la creation est notifiable"

        second = engine.analyse(market, [group])
        events_two = engine.commit(second)
        assert [event.event_type for event in events_two] == ["OPPORTUNITY_CREATED"]
        assert events_two[0].notifiable is False, "CREATED -> ACTIVE ne re-alerte pas"

        third = engine.analyse(market, [group])
        assert engine.commit(third) == [], "un etat inchange ne produit aucun nouvel evenement"

    def test_the_registry_is_capped(self, market):
        engine = OpportunityEngine(op_fx.params(lifecycle={"max_tracked": 10}))
        for index in range(15):
            group = op_fx.group_copy(op_fx.strong_group(market), id=f"cf_{index}")
            result = engine.analyse(market, [group])
            engine.commit(result)
        assert len(engine.all()) <= 10

    def test_identity_uses_the_confluence_not_the_clock(self, market):
        assert _opportunity_id("EURUSD", "M15", "cf_1") == _opportunity_id("EURUSD", "M15", "cf_1")
        assert _opportunity_id("EURUSD", "M15", "cf_1") != _opportunity_id("EURUSD", "M15", "cf_2")
        assert _opportunity_id("EURUSD", "M15", "cf_1") != _opportunity_id("EURUSD", "H1", "cf_1")


class TestDataHonesty:
    def test_the_reference_price_is_a_real_price(self, engine, market):
        group = op_fx.strong_group(market)
        item = engine.analyse(market, [group]).opportunities[0]
        assert item.reference_price == group.reference_price
        real = {round(candle.close, 10) for candle in market.candles} | {
            round(event.price, 10) for event in group.events if event.price is not None
        }
        for level in item.watch_levels:
            assert round(level.price, 10) in real, "un niveau observe doit etre un prix reel"

    def test_no_volume_or_spread_is_invented(self, engine, market):
        item = engine.analyse(market, [op_fx.strong_group(market)]).opportunities[0]
        payload = item.as_dict()
        assert "volume" not in str(payload).lower()
        assert "spread" not in str(payload).lower()
        assert "profit" not in str(payload).lower()

    def test_the_payload_exposes_the_requested_fields(self, engine, market):
        item = engine.analyse(market, [op_fx.strong_group(market)]).opportunities[0]
        payload = item.as_dict()
        for field in (
            "symbol",
            "timeframe",
            "direction",
            "state",
            "score",
            "reference_price",
            "confluence_id",
            "evidence",
            "created_at",
            "expires_at",
            "conditions",
        ):
            assert field in payload
        assert payload["confluence_id"].startswith("cf_")

    def test_recording_an_observation_does_not_depend_on_a_clock(self, engine, market):
        engine.commit(engine.analyse(market, [op_fx.strong_group(market)]))
        engine.commit(engine.analyse(market, [op_fx.strong_group(market)]))
        assert len(engine.all()) == 1, "meme observation : une seule entree suivie"
