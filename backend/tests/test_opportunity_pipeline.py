"""Phase 6 - opportunity service / API / stream wiring.

The engine logic is covered by ``test_opportunity_engine.py``; this file checks the
application wiring: the event bus, the persistence, the REST surface, the
WebSocket snapshot, the alert hand-off to the outbox and the guarantee that the
scanner keeps running when any of those fail.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.db.repository import OpportunityRepository
from app.main import app as fastapi_app
from app.opportunities.engine import OpportunityEngine
from app.schemas.events import EventType
from app.services.opportunities import OpportunityService
from app.services.events import EventBus
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
def bus():
    return EventBus()


@pytest.fixture
def service(bus, tmp_path):
    return OpportunityService(
        engine=OpportunityEngine(op_fx.params()),
        bus=bus,
        repository=OpportunityRepository(session_factory=_session_factory(tmp_path)),
        event_repository=None,
    )


class TestService:
    def test_a_named_observation_is_published_on_the_shared_bus(self, service, bus, market):
        result = service.analyse(market, [op_fx.strong_group(market)], publish=True)
        assert result.opportunities and service.errors == []
        event = bus.history(limit=10)[-1]
        assert event.event_type == EventType.OPPORTUNITY_CREATED
        assert event.metadata["trading_signal"] is False
        assert event.metadata["order_execution"] is False
        assert event.metadata["confluence_id"] == result.opportunities[0].confluence_id
        assert event.metadata["alert_id"].startswith("al_")
        assert event.metadata["conditions"], "les criteres verifies sont transmis"
        assert event.price == result.opportunities[0].reference_price

    def test_a_refusal_is_stored_and_shown_but_never_published(self, service, bus, market):
        weak = op_fx.group_copy(
            op_fx.strong_group(market), state=cf_fx.state_value("CONTRADICTED")
        )
        result = service.analyse(market, [weak], publish=True)
        assert result.opportunities[0].direction == "NO_TRADE"
        assert bus.history(limit=10) == [], "un refus ne reveille personne"
        assert service.repository.count() == 1, "mais il reste consultable"

    def test_persistence_is_idempotent_across_ticks(self, service, market):
        group = op_fx.strong_group(market)
        for _ in range(3):
            service.analyse(market, [group])
        assert service.repository.count() == len(service.tracked())

    def test_the_outbox_is_handed_the_alert_without_blocking(self, service, market):
        queued: list[tuple[str, str]] = []

        class Outbox:
            def enqueue_opportunity(self, opportunity, event_type):
                queued.append((opportunity.id, event_type))
                return True

        service.outbox = Outbox()
        service.analyse(market, [op_fx.strong_group(market)])
        assert queued and queued[0][1] == "OPPORTUNITY_CREATED"
        assert service.alerts_queued == 1

    def test_a_broken_outbox_never_stops_the_service(self, service, market):
        class Outbox:
            def enqueue_opportunity(self, opportunity, event_type):
                raise RuntimeError("telegram down")

        service.outbox = Outbox()
        result = service.analyse(market, [op_fx.strong_group(market)])
        assert result.opportunities, "l'analyse aboutit malgre l'outbox"
        assert service.errors and "telegram down" in service.errors[0]

    def test_a_broken_engine_never_stops_the_scanner(self, bus, tmp_path, market):
        class Broken(OpportunityEngine):
            def analyse(self, *args, **kwargs):  # noqa: D102
                raise RuntimeError("boom")

        service = OpportunityService(
            engine=Broken(op_fx.params()),
            bus=bus,
            repository=OpportunityRepository(session_factory=_session_factory(tmp_path)),
        )
        result = service.analyse(market, [op_fx.strong_group(market)])
        assert result.opportunities == []
        assert service.errors and "boom" in service.errors[0]

    def test_stats_and_overview_report_the_real_numbers(self, service, market):
        service.analyse(market, [op_fx.strong_group(market)])
        stats = service.stats()
        assert stats["runs"] == 1
        assert stats["bars_analysed"] == 73
        assert stats["persisted"] == 1
        assert stats["persisted_by_direction"]["BUY"] == 1
        overview = service.overview("EURUSD", "M15")
        assert overview["direction"] == "BUY"
        assert overview["max_score"] == 10.0
        assert overview["named"] == 1


class TestApi:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        container = Container.build()
        container.opportunities = OpportunityService(
            engine=OpportunityEngine(op_fx.params()),
            bus=container.bus,
            repository=OpportunityRepository(session_factory=_session_factory(tmp_path)),
        )
        fastapi_app.state.container = container
        with TestClient(fastapi_app) as test_client:
            yield test_client, container

    def test_list_is_empty_before_any_observation(self, client):
        test_client, _ = client
        body = test_client.get("/api/opportunities").json()
        assert body["count"] == 0 and body["opportunities"] == []
        assert body["trading_signal"] is False and body["order_execution"] is False
        assert body["engines"]["OPPORTUNITY_ENGINE"] == "ENABLED"

    def test_list_and_detail_expose_the_conditions(self, client, market):
        test_client, container = client
        result = container.opportunities.analyse(market, [op_fx.strong_group(market)])
        identifier = result.opportunities[0].id

        body = test_client.get(f"/api/opportunities?symbol=EURUSD&timeframe=M15").json()
        assert body["count"] == 1
        assert body["directions"] == {"BUY": 1}
        assert body["opportunities"][0]["id"] == identifier

        detail = test_client.get(f"/api/opportunities/{identifier}").json()
        assert detail["conditions"]
        assert detail["confluence_id"].startswith("cf_")
        assert detail["no_trade_reason"] is None

    def test_detail_falls_back_to_the_stored_row_then_404(self, client, market):
        test_client, container = client
        result = container.opportunities.analyse(market, [op_fx.strong_group(market)])
        identifier = result.opportunities[0].id
        container.opportunities.engine.clear()
        stored = test_client.get(f"/api/opportunities/{identifier}")
        assert stored.status_code == 200 and stored.json()["id"] == identifier
        assert test_client.get("/api/opportunities/op_inconnu").status_code == 404

    def test_overview_and_history_and_params(self, client, market):
        test_client, container = client
        container.opportunities.analyse(market, [op_fx.strong_group(market)])

        overview = test_client.get("/api/opportunities/overview?symbol=EURUSD&timeframe=M15").json()
        assert overview["direction"] == "BUY" and overview["max_score"] == 10.0

        history = test_client.get("/api/opportunities/history?limit=5").json()
        assert history["count"] >= 1 and history["opportunities"][0]["id"].startswith("op_")

        params = test_client.get("/api/opportunities/params").json()
        assert params["groups"] == ["conditions", "weights", "lifecycle"]
        assert params["params"]["weights"]["liquidity"] == 2.0
        # the note must DENY the false reading explicitly, not merely avoid the word
        note = params["note"].lower()
        assert "ce n'est pas une probabilite de reussite" in note

    def test_params_are_adjustable_at_runtime(self, client):
        test_client, container = client
        response = test_client.patch(
            "/api/opportunities/params", json={"overrides": {"conditions": {"watch_score": 4.5}}}
        )
        assert response.status_code == 200
        assert "conditions.watch_score=4.5" in response.json()["applied"]
        assert container.opportunities.params().conditions.watch_score == 4.5
        container.opportunities.params().conditions.watch_score = 5.0

    def test_filters_split_directions_and_states(self, client, market):
        test_client, container = client
        container.opportunities.analyse(market, [op_fx.strong_group(market)])
        container.opportunities.analyse(
            market,
            [
                op_fx.group_copy(
                    op_fx.strong_group(market),
                    id="cf_baisse",
                    direction="BEARISH",
                    state=cf_fx.state_value("CONTRADICTED"),
                )
            ],
        )
        assert test_client.get("/api/opportunities?direction=NO_TRADE").json()["count"] == 1
        assert test_client.get("/api/opportunities?direction=BUY").json()["count"] == 1
        assert test_client.get("/api/opportunities?state=CREATED").json()["count"] == 1


class TestStreamSnapshot:
    def test_snapshot_is_none_when_nothing_is_tracked(self, tmp_path):
        from app.api import stream

        container = Container.build()
        container.opportunities = OpportunityService(
            engine=OpportunityEngine(op_fx.params()),
            bus=container.bus,
            repository=OpportunityRepository(session_factory=_session_factory(tmp_path)),
        )
        assert stream._opportunity_snapshot(container, "EURUSD", "M15") is None

    def test_snapshot_carries_the_observations_for_a_reconnecting_dashboard(self, tmp_path, market):
        from app.api import stream

        container = Container.build()
        container.opportunities = OpportunityService(
            engine=OpportunityEngine(op_fx.params()),
            bus=container.bus,
            repository=OpportunityRepository(session_factory=_session_factory(tmp_path)),
        )
        container.opportunities.analyse(market, [op_fx.strong_group(market)])
        snapshot = stream._opportunity_snapshot(container, "EURUSD", "M15")
        assert snapshot is not None
        assert snapshot.event_type is EventType.OPPORTUNITY_SNAPSHOT
        assert snapshot.metadata["opportunities"]
        assert snapshot.metadata["overview"]["direction"] == "BUY"
        assert snapshot.metadata["trading_signal"] is False


class TestScannerStep:
    def test_the_scanner_runs_the_opportunity_step_every_tick(self, monkeypatch, market):
        """The lifecycle is evaluated on every tick, not only when a confluence appears."""
        from app.services import scanner as scanner_module

        calls: list[int] = []
        container = Container.build()
        original = container.opportunities.analyse

        def wrapper(series, groups, **kwargs):
            calls.append(len(groups))
            return original(series, groups, **kwargs)

        container.opportunities.analyse = wrapper
        scanner = container.scanner
        scanner.opportunities = container.opportunities
        scanner._run_opportunities(market, [], "EURUSD", "M15")
        scanner._run_opportunities(market, [op_fx.strong_group(market)], "EURUSD", "M15")
        assert calls == [0, 1], "l'etape tourne meme sans confluence nouvelle"
        assert scanner.opportunities.errors == []


def _session_factory(tmp_path):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path/'opportunities.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

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

    return scope
