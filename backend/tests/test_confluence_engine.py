"""Confluence Engine tests (Phase 5).

What is checked here, and nothing else:

* normalisation (5.1): identity preserved, documented dimension map, real prices;
* temporal alignment (5.2): an event outside the window / the price band / the
  maximum age never joins a confluence;
* direction alignment (5.3): opposing readings are reported, never merged;
* score (5.4): one point per dimension, traceable, contradictions charged;
* states (5.5) and multi-timeframe (5.6);
* explicability (5.7): ``why`` / ``against`` are always available;
* identity and lifecycle (5.8): stable id, updated in place, expired once.
"""

from __future__ import annotations

import pytest

from app.confluence.engine import ConfluenceEngine, OBSERVED_STATES
from app.confluence.models import ConfluenceState
from app.confluence.normalizer import dimension_for, normalise, reference_price
from app.confluence.params import ConfluenceParams
from app.confluence.scoring import score_group
from app.schemas.events import DetectionCategory, DetectionStatus
from tests import confluence_fixtures as fx


@pytest.fixture
def params() -> ConfluenceParams:
    return ConfluenceParams()


@pytest.fixture
def engine(params) -> ConfluenceEngine:
    return ConfluenceEngine(params)


@pytest.fixture
def market():
    """100 calm bars: a real series for the engine to measure bars and ATR on."""
    bars = fx.calm(70) + [
        fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
        fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
        fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
    ]
    return fx.series(bars)


# ------------------------------------------------------------ 5.1 normalisation
class TestNormalisation:
    def test_identity_and_timeframe_are_preserved(self):
        item = fx.bos("smc_bos_1", time=fx.bar_time(71), price=1.1)
        event = normalise([item])[0]
        assert event.id == item.id, "l'identifiant de la detection doit survivre"
        assert event.timeframe == "M15"
        assert event.source == "SMC_ICT"
        assert event.type == "BOS"
        assert event.timestamp == fx.bar_time(71)

    def test_documented_dimension_map(self):
        assert dimension_for("BOS", "SMC_ICT") == "STRUCTURE"
        assert dimension_for("MSS", "SMC_ICT") == "STRUCTURE"
        assert dimension_for("LIQUIDITY_SWEEP", "SMC_ICT") == "LIQUIDITY"
        assert dimension_for("EQUAL_HIGH", "SMC_ICT") == "LIQUIDITY"
        assert dimension_for("LIQUIDITY_POOL_ESTIMATE", "SMC_ICT") == "LIQUIDITY"
        assert dimension_for("BULLISH_FVG", "SMC_ICT") == "IMBALANCE"
        assert dimension_for("BEARISH_ORDER_BLOCK", "SMC_ICT") == "IMBALANCE"
        assert dimension_for("BREAKER_BLOCK", "SMC_ICT") == "IMBALANCE"
        assert dimension_for("DISPLACEMENT", "SMC_ICT") == "DISPLACEMENT"
        assert dimension_for("PREMIUM", "SMC_ICT") == "PREMIUM_DISCOUNT"
        assert dimension_for("BULLISH_ENGULFING", "PRICE_ACTION") == "PRICE_ACTION"
        assert dimension_for("REJECTION", "PRICE_ACTION") == "PRICE_ACTION"
        assert dimension_for("DOUBLE_TOP", "CHARTISTE") == "CHARTISTE"

    def test_unknown_pattern_falls_back_to_its_engine(self):
        assert dimension_for("MARUBOZU", "PRICE_ACTION") == "PRICE_ACTION"
        assert dimension_for("SOMETHING_NEW", "CHARTISTE") == "CHARTISTE"
        assert dimension_for("SOMETHING_NEW", "SMC_ICT") == "STRUCTURE"

    def test_inactive_objects_are_dropped_and_can_be_kept_on_request(self):
        alive = fx.bos("smc_1", time=fx.bar_time(71), price=1.1)
        dead = fx.bos("smc_2", time=fx.bar_time(71), price=1.1, status=DetectionStatus.EXPIRED)
        assert [event.id for event in normalise([alive, dead])] == ["smc_1"]
        assert len(normalise([alive, dead], keep_inactive=True)) == 2

    def test_price_comes_from_the_real_drawing_only(self):
        with_level = fx.bos("smc_1", time=fx.bar_time(71), price=1.12345)
        without = fx.bos("smc_2", time=fx.bar_time(71), price=None)
        assert reference_price(with_level) == pytest.approx(1.12345)
        assert reference_price(without) is None, "aucun prix inventé sans niveau reel"

    def test_filtering_by_symbol_and_timeframe(self):
        items = [
            fx.bos("a", time=fx.bar_time(71), price=1.1),
            fx.bos("b", time=fx.bar_time(71), price=1.1, timeframe="H1"),
            fx.bos("c", time=fx.bar_time(71), price=1.1, symbol="GBPUSD"),
        ]
        kept = normalise(items, symbol="EURUSD", timeframe="M15")
        assert [event.id for event in kept] == ["a"]


# ------------------------------------------------------------------- 5.4 score
class TestScore:
    def test_one_dimension_earns_its_weight_once(self, params):
        events = normalise(
            [
                fx.fvg("f1", time=fx.bar_time(71), price=1.1),
                fx.fvg("f2", time=fx.bar_time(71), price=1.1),
                fx.order_block("ob1", time=fx.bar_time(71), price=1.1),
            ]
        )
        components, contradictions, total = score_group("BULLISH", events, [], params)
        assert len(components) == 1, "trois lectures d'un meme type = une dimension"
        assert components[0].dimension == "IMBALANCE"
        assert components[0].points == params.weights.imbalance
        assert sorted(components[0].events) == ["f1", "f2", "ob1"], "les evenements restent traçables"
        assert total == params.weights.imbalance
        assert contradictions == []

    def test_score_is_the_sum_of_the_dimensions(self, params, engine, market):
        events = fx.bullish_stack(fx.bar_time(71))
        result = engine.analyse(market, events)
        group = result.groups[0]
        assert group.score == pytest.approx(2.0 + 2.0 + 1.0 + 1.0 + 1.0)  # structure, liquidite, imbalance, PA, chartiste
        assert group.dimensions == ["STRUCTURE", "LIQUIDITY", "IMBALANCE", "PRICE_ACTION", "CHARTISTE"]
        assert group.max_score == params.max_score() == 10.0

    def test_contradictions_are_charged_and_traceable(self, params):
        aligned = normalise([fx.bos("b1", time=fx.bar_time(71), price=1.1)])
        opposing = normalise([fx.choch("c1", direction="BEARISH", time=fx.bar_time(71), price=1.1)])
        components, contradictions, total = score_group("BULLISH", aligned, opposing, params)
        assert len(contradictions) == 1
        assert contradictions[0].dimension == "STRUCTURE"
        assert contradictions[0].points == -params.states.expected_per_dimension
        assert contradictions[0].events == ["c1"]
        assert total == pytest.approx(params.weights.structure - params.states.expected_per_dimension)

    def test_neutral_readings_earn_nothing(self, params):
        events = normalise([fx.pool("p1", time=fx.bar_time(71), price=1.1)])
        components, _, total = score_group("BULLISH", [event for event in events if event.direction == "BULLISH"], [], params)
        assert components == [] and total == 0.0

    def test_score_never_exceeds_the_maximum(self, params, engine, market):
        events = fx.bullish_stack(fx.bar_time(71)) + [
            fx.displacement("d1", time=fx.bar_time(71), price=1.1),
            fx.premium_discount("pd1", time=fx.bar_time(71), price=1.1),
        ]
        result = engine.analyse(market, events)
        assert result.groups[0].score <= params.max_score()


# ------------------------------------------------------------------- 5.2 / 5.3
class TestAlignment:
    def test_an_old_event_never_joins_a_fresh_confluence(self, engine, market):
        fresh = fx.bullish_stack(fx.bar_time(72))
        ancient = [fx.bos("old_bos", time=fx.bar_time(20), price=1.1)]
        result = engine.analyse(market, fresh + ancient)
        ids = {event.id for group in result.groups for event in group.events}
        assert "old_bos" not in ids, "un evenement perime ne doit pas ressusciter"

    def test_events_outside_the_bar_window_are_excluded(self, params, market):
        params.global_.window_bars = 2
        engine = ConfluenceEngine(params)
        events = [
            fx.bos("old", time=fx.bar_time(65), price=1.1),
            fx.fvg("new", time=fx.bar_time(72), price=1.1),
        ]
        result = engine.analyse(market, events)
        ids = {event.id for group in result.groups for event in group.events}
        assert "new" in ids and "old" not in ids

    def test_events_far_away_in_price_are_excluded(self, params, market):
        events = [
            fx.bos("near", time=fx.bar_time(72), price=1.1),
            fx.fvg("far", time=fx.bar_time(72), price=1.5),  # 4000 pips away
        ]
        engine = ConfluenceEngine(params)
        result = engine.analyse(market, events)
        ids = {event.id for group in result.groups for event in group.events}
        assert "near" in ids and "far" not in ids

    def test_opposite_directions_are_reported_separately(self, engine, market):
        result = engine.analyse(market, fx.bullish_stack(fx.bar_time(72)) + [
            fx.choch("bear_1", direction="BEARISH", time=fx.bar_time(72), price=1.1),
            fx.fvg("bear_2", direction="BEARISH", time=fx.bar_time(72), price=1.1),
            fx.price_action("bear_3", "BEARISH_ENGULFING", direction="BEARISH", time=fx.bar_time(72), price=1.1),
        ])
        directions = {group.direction for group in result.groups}
        assert directions == {"BULLISH", "BEARISH"}, "les deux camps doivent rester visibles"
        bullish = next(group for group in result.groups if group.direction == "BULLISH")
        assert bullish.state == ConfluenceState.CONTRADICTED.value
        assert bullish.contradictions, "la contradiction est explicite"
        assert any("oppose" in line for line in bullish.against)

    def test_a_neutral_only_series_is_no_confluence(self, engine, market):
        result = engine.analyse(market, [fx.pool("pool_1", time=fx.bar_time(72), price=1.1)])
        assert len(result.groups) == 1
        assert result.groups[0].state == ConfluenceState.NO_CONFLUENCE.value
        assert result.groups[0].direction == "NEUTRAL"


# --------------------------------------------------------------------- 5.5 states
class TestStates:
    def test_single_event_is_no_confluence(self, engine, market):
        result = engine.analyse(market, [fx.bos("only", time=fx.bar_time(72), price=1.1)])
        assert result.groups[0].state == ConfluenceState.NO_CONFLUENCE.value

    def test_watch_starts_at_the_watch_threshold(self, engine, market):
        """2 points restent sous le seuil WATCH ; 3 points y entrent (etat explicite)."""
        below = engine.analyse(market, [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ])
        assert below.groups[0].score == 2.0
        assert below.groups[0].state == ConfluenceState.NO_CONFLUENCE.value

        above = engine.analyse(market, [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
            fx.chartist("ct1", "SUPPORT", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ])
        assert above.groups[0].score == 3.0
        assert above.groups[0].state == ConfluenceState.WATCH.value

    def test_full_stack_is_a_strong_confluence(self, engine, market):
        events = fx.bullish_stack(fx.bar_time(72)) + [
            fx.displacement("d1", time=fx.bar_time(72), price=1.1),
            fx.premium_discount("pd1", time=fx.bar_time(72), price=1.1),
        ]
        result = engine.analyse(market, events)
        group = result.groups[0]
        assert group.score == 9.0, "structure 2 + liquidite 2 + imbalance 1 + PA 1 + chartiste 1 + displacement 1 + premium/discount 1"
        assert group.state == ConfluenceState.STRONG_CONFLUENCE.value
        assert group.state in OBSERVED_STATES

    def test_strong_requires_several_dimensions(self, params, market):
        params.states.strong_min_dimensions = 6
        params.weights.imbalance = 8.0  # a single dimension can reach the score
        engine = ConfluenceEngine(params)
        result = engine.analyse(market, [fx.fvg("f1", time=fx.bar_time(72), price=1.1)])
        assert result.groups[0].state != ConfluenceState.STRONG_CONFLUENCE.value


# ------------------------------------------------------------- 5.6 multi-timeframe
class TestMultiTimeframe:
    def test_a_slower_timeframe_adds_its_own_dimension(self, engine, market):
        events = [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "BULLISH_ENGULFING", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ]
        context_time = market.candles[-1].time
        context = {"H1": [fx.bos("h1_bos", time=context_time, price=1.1, timeframe="H1")]}
        result = engine.analyse(market, events, context=context)
        group = result.groups[0]
        assert "MULTI_TIMEFRAME" in group.dimensions
        assert group.score == pytest.approx(1.0 + 1.0 + 1.0)
        assert any("H1" in line for line in group.why), "le timeframe du contexte est ecrit"
        assert group.multi_timeframe[0]["timeframe"] == "H1"
        assert group.multi_timeframe[0]["aligned"] == ["h1_bos"]

    def test_an_opposing_higher_timeframe_is_a_contradiction(self, engine, market):
        events = fx.bullish_stack(fx.bar_time(72))
        context_time = market.candles[-1].time
        context = {"H1": [fx.bos("h1_bear", direction="BEARISH", time=context_time, price=1.1, timeframe="H1")]}
        result = engine.analyse(market, events, context=context)
        group = result.groups[0]
        assert group.state == ConfluenceState.CONTRADICTED.value
        assert any(component.dimension == "STRUCTURE" for component in group.contradictions)
        assert any("H1" in line for line in group.against)

    def test_a_faster_timeframe_is_never_used_as_context(self, engine, market):
        events = [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ]
        context = {"M5": [fx.bos("m5_bos", time=market.candles[-1].time, price=1.1, timeframe="M5")]}
        result = engine.analyse(market, events, context=context)
        assert "MULTI_TIMEFRAME" not in result.groups[0].dimensions

    def test_multi_timeframe_can_be_disabled(self, params, market):
        params.multi_timeframe.enabled = False
        engine = ConfluenceEngine(params)
        events = [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ]
        context = {"H1": [fx.bos("h1_bos", time=market.candles[-1].time, price=1.1, timeframe="H1")]}
        result = engine.analyse(market, events, context=context)
        assert "MULTI_TIMEFRAME" not in result.groups[0].dimensions


# ------------------------------------------------------------------ 5.7 / 5.8
class TestIdentityAndLifecycle:
    def test_the_id_is_deterministic_and_anchored_on_a_real_event(self, engine, market):
        events = [
            fx.bos("anchor", time=fx.bar_time(72), price=1.1),
            fx.fvg("second", time=fx.bar_time(72), price=1.1),
        ]
        first = ConfluenceEngine(ConfluenceParams()).analyse(market, events).groups[0]
        second = ConfluenceEngine(ConfluenceParams()).analyse(market, events).groups[0]
        assert first.id == second.id and first.id.startswith("cf_")
        assert first.dedup_key == first.id

    def test_a_new_event_joins_the_same_confluence(self, engine, market):
        base = [fx.bos("anchor", time=fx.bar_time(71), price=1.1)]
        engine.commit(engine.analyse(market, base))
        first_id = engine.all()[0].id

        joined = base + [fx.fvg("later", time=fx.bar_time(72), price=1.1)]
        result = engine.analyse(market, joined)
        engine.commit(result)
        assert result.groups[0].id == first_id, "la confluence garde son identite"
        assert result.groups[0].generation == 3 or result.groups[0].generation >= 2
        assert {event.id for event in result.groups[0].events} >= {"anchor", "later"}

    def test_transitions_are_published_once_each(self, engine, market):
        events = [
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("pa1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
            fx.chartist("ct1", "SUPPORT", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ]
        first = engine.commit(engine.analyse(market, events))
        assert [event.event_type for event in first] == ["CONFLUENCE_DETECTED"]

        same = engine.commit(engine.analyse(market, events))
        assert same == [], "aucun evenement quand rien ne change"

        upgraded = engine.analyse(
            market,
            events + [fx.bos("b1", time=fx.bar_time(72), price=1.1), fx.sweep("s1", time=fx.bar_time(72), price=1.1)],
        )
        transitions = engine.commit(upgraded)
        assert [event.event_type for event in transitions] == ["CONFLUENCE_UPDATED"]
        assert transitions[0].previous_state == ConfluenceState.WATCH.value

    def test_a_contradiction_is_its_own_event(self, engine, market):
        bullish = [
            fx.bos("b1", time=fx.bar_time(72), price=1.1),
            fx.fvg("f1", time=fx.bar_time(72), price=1.1),
            fx.price_action("p1", "HAMMER", direction="BULLISH", time=fx.bar_time(72), price=1.1),
        ]
        engine.commit(engine.analyse(market, bullish))
        transitions = engine.commit(
            engine.analyse(
                market,
                bullish
                + [
                    fx.choch("c1", direction="BEARISH", time=fx.bar_time(72), price=1.1),
                    fx.fvg("bf1", direction="BEARISH", time=fx.bar_time(72), price=1.1),
                ],
            )
        )
        assert {event.event_type for event in transitions} == {"CONFLUENCE_CONTRADICTED"}
        bullish = next(event for event in transitions if event.group.direction == "BULLISH")
        assert bullish.group.state == ConfluenceState.CONTRADICTED.value
        assert bullish.previous_state == ConfluenceState.WATCH.value
        assert any(component.dimension == "STRUCTURE" for component in bullish.group.contradictions)
        assert any(component.dimension == "IMBALANCE" for component in bullish.group.contradictions), (
            "les deux dimensions opposees sont nommees (structure et imbalance)"
        )

    def test_expiry_is_published_once_then_dropped(self, params, market):
        params.global_.validity_bars = 2
        engine = ConfluenceEngine(params)
        engine.commit(engine.analyse(market, [fx.bos("b1", time=fx.bar_time(72), price=1.1)]))
        assert len(engine.all()) == 1

        later = fx.series(fx.calm(70) + [
            fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
            fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
            fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
            fx.BarSpec(open=1.4, high=1.5, low=1.3, close=1.45),
            fx.BarSpec(open=1.45, high=1.5, low=1.4, close=1.48),
            fx.BarSpec(open=1.48, high=1.5, low=1.45, close=1.49),
        ])
        fresh_elsewhere = [fx.fvg("other", direction="BEARISH", time=fx.bar_time(75), price=1.45)]
        transitions = engine.commit(engine.analyse(later, fresh_elsewhere))
        assert [event.event_type for event in transitions] == ["CONFLUENCE_EXPIRED"]

    def test_explainability_is_always_available(self, engine, market):
        result = engine.analyse(market, fx.bullish_stack(fx.bar_time(72)))
        group = result.groups[0]
        assert group.why and group.against
        assert any("Structure" in line for line in group.why)
        assert all("[+" in line for line in group.why)
        assert group.against[-1].startswith("aucun element oppose") or "neutre" in group.against[-1]

    def test_registry_cap_is_enforced(self, params, market):
        params.global_.max_tracked = 3
        engine = ConfluenceEngine(params)
        for index in range(6):
            engine.commit(
                engine.analyse(market, [fx.bos(f"b{index}", time=fx.bar_time(66 + index), price=1.1)])
            )
        assert len(engine.all()) <= 3


# ------------------------------------------------------------------- persistence
class TestPersistence:
    def test_groups_are_saved_and_updated_without_duplicates(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from contextlib import contextmanager

        import app.db.models  # noqa: F401
        from app.db.base import Base
        from app.db.repository import ConfluenceRepository

        engine_db = create_engine(f"sqlite:///{tmp_path/'cf.db'}", future=True)
        Base.metadata.create_all(engine_db)
        factory = sessionmaker(bind=engine_db, autoflush=False, expire_on_commit=False, future=True)

        @contextmanager
        def scope():
            session = factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        repo = ConfluenceRepository(session_factory=scope)
        cf_engine = ConfluenceEngine(ConfluenceParams())
        market = fx.series(fx.calm(70) + [
            fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
            fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
            fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
        ])
        events = fx.bullish_stack(fx.bar_time(72))

        result = cf_engine.analyse(market, events)
        assert repo.save_many(result.groups) == len(result.groups)
        assert repo.save_many(result.groups) == len(result.groups)
        assert repo.count() == len(result.groups), "mise a jour en place, aucun doublon"

        stored = repo.get(result.groups[0].id)
        assert stored["score"] == result.groups[0].score
        assert stored["events"], "les evenements sources sont conserves"
        assert stored["components"], "le detail du score est conserve"
        assert stored["why"] and stored["against"]
        engine_db.dispose()
