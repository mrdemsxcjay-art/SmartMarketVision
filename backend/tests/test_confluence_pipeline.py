"""Confluence service / API / stream tests (Phase 5).

The engine logic is covered by ``test_confluence_engine.py``; this file checks the
application wiring: the event bus, the persistence, the REST surface and the
WebSocket snapshot. It also runs the three existing engines and feeds their real
output into the confluence engine, which is exactly what the scanner does.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.confluence.engine import ConfluenceEngine
from app.confluence.params import ConfluenceParams
from app.container import Container
from app.db.repository import ConfluenceRepository
from app.main import app as fastapi_app
from app.patterns.engine import ChartPatternEngine
from app.patterns.params import PatternParams
from app.price_action.engine import PriceActionEngine
from app.price_action.params import PriceActionParams
from app.schemas.events import EventType
from app.services.confluence import ConfluenceService
from app.services.events import EventBus
from app.smc_ict.engine import SmcIctEngine
from app.smc_ict.params import SmcIctParams
from tests import confluence_fixtures as fx

FORBIDDEN = ("BUY", "SELL", "ENTRY", "STOP LOSS", "TAKE PROFIT", "ORDER")


@pytest.fixture
def market():
    bars = fx.calm(70) + [
        fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
        fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
        fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
    ]
    return fx.series(bars)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


class TestService:
    def test_it_publishes_observed_states_on_the_shared_bus(self, market, bus, tmp_path):
        service = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()),
            bus=bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
            event_repository=None,
        )
        result = service.analyse(market, fx.bullish_stack(market.candles[-1].time), publish=True)

        assert result.groups and service.errors == []
        published = bus.history(limit=10)
        assert published, "une confluence observee doit etre publiee sur le bus"
        event = published[-1]
        assert event.event_type in (EventType.CONFLUENCE_DETECTED, EventType.CONFLUENCE_UPDATED)
        assert event.metadata["trading_signal"] is False
        assert event.metadata["confluence_id"] == result.groups[0].id
        assert event.metadata["events"], "les identifiants des detections sources sont transmis"

    def test_no_node_is_no_event(self, market, bus, tmp_path):
        service = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()),
            bus=bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
            event_repository=None,
        )
        service.analyse(market, [fx.fvg("f1", time=market.candles[-1].time, price=1.1)], publish=True)
        assert bus.history(limit=10) == [], "aucune confluence observee : rien n'est publie"

    def test_persistence_is_idempotent_across_ticks(self, market, bus, tmp_path):
        repository = ConfluenceRepository(session_factory=_session_factory(tmp_path))
        service = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()), bus=bus, repository=repository
        )
        events = fx.bullish_stack(market.candles[-1].time)
        for _ in range(3):
            service.analyse(market, events, publish=True)
        assert repository.count() == len(service.tracked()), "une ligne par confluence, mise a jour en place"

    def test_no_trade_vocabulary_in_the_payload(self, market, bus, tmp_path):
        repository = ConfluenceRepository(session_factory=_session_factory(tmp_path))
        service = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()), bus=bus, repository=repository
        )
        result = service.analyse(market, fx.bullish_stack(market.candles[-1].time), publish=True)
        payload = result.groups[0].as_dict()
        text = str(payload).upper()
        for word in ("BUY", "SELL", "ENTRY", "TAKE PROFIT", "STOP LOSS"):
            assert word not in text, f"{word} ne doit jamais apparaitre dans une confluence"

    def test_engine_failure_never_kills_the_scanner(self, market, bus, tmp_path):
        class Broken(ConfluenceEngine):
            def analyse(self, *args, **kwargs):  # noqa: D102
                raise RuntimeError("boom")

        service = ConfluenceService(
            engine=Broken(ConfluenceParams()),
            bus=bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
        )
        result = service.analyse(market, [], publish=True)
        assert result.groups == []
        assert service.errors and "boom" in service.errors[0]


class TestThreeEnginesIntegration:
    def test_confluence_consumes_the_real_engines(self, market):
        """The three engines run first; the confluence reads what they published."""
        chartist = ChartPatternEngine(PatternParams())
        price_action = PriceActionEngine(PriceActionParams())
        smc = SmcIctEngine(SmcIctParams())

        ct_result = chartist.analyse(market)
        chartist.commit(ct_result)
        pa_result = price_action.analyse(market, chartist=list(chartist.all()))
        price_action.commit(pa_result)
        smc_result = smc.analyse(market)
        smc.commit(smc_result)

        detections = list(chartist.all()) + list(price_action.all()) + list(smc.all())
        engine = ConfluenceEngine(ConfluenceParams())
        result = engine.analyse(market, detections)
        engine.commit(result)

        assert result.events_considered == len(detections)
        for group in result.groups:
            assert all(
                event.source in ("CHARTISTE", "PRICE_ACTION", "SMC_ICT") for event in group.events
            ), "chaque evenement garde l'engine dont il vient"
            assert all(event.timeframe == "M15" for event in group.events)
            for component in group.components:
                assert component.points > 0 and component.events


class TestApi:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        container = Container.build()
        container.confluence = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()),
            bus=container.bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
        )
        fastapi_app.state.container = container
        with TestClient(fastapi_app) as test_client:
            yield test_client, container

    def test_list_endpoint_is_empty_and_honest(self, client):
        test_client, _ = client
        response = test_client.get("/api/confluence")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["confluences"] == []
        assert body["trading_signal"] is False

    def test_detail_returns_live_then_stored_then_404(self, client, market):
        test_client, container = client
        result = container.confluence.analyse(
            market, fx.bullish_stack(market.candles[-1].time), publish=True
        )
        group_id = result.groups[0].id

        live = test_client.get(f"/api/confluence/{group_id}")
        assert live.status_code == 200
        assert live.json()["score"] == result.groups[0].score
        assert live.json()["components"], "le detail du score est expose"
        assert live.json()["why"] and live.json()["against"]

        container.confluence.engine.clear()  # stored row only
        stored = test_client.get(f"/api/confluence/{group_id}")
        assert stored.status_code == 200 and stored.json()["id"] == group_id

        assert test_client.get("/api/confluence/cf_inconnu").status_code == 404

    def test_overview_and_params(self, client, market):
        test_client, container = client
        container.confluence.analyse(market, fx.bullish_stack(market.candles[-1].time))

        overview = test_client.get("/api/confluence/overview?symbol=EURUSD&timeframe=M15").json()
        assert overview["symbol"] == "EURUSD"
        assert overview["max_score"] == 10.0
        assert overview["state"] in ("WATCH", "CONFLUENCE", "STRONG_CONFLUENCE")

        params = test_client.get("/api/confluence/params").json()
        assert params["groups"] == ["globals", "states", "weights", "multi_timeframe"]
        assert params["params"]["weights"]["structure"] == 2.0
        assert "probabilite" not in params["note"].lower()

    def test_params_can_be_adjusted_at_runtime(self, client):
        test_client, container = client
        response = test_client.patch(
            "/api/confluence/params", json={"overrides": {"globals": {"window_bars": 9}}}
        )
        assert response.status_code == 200
        assert "globals.window_bars=9" in response.json()["applied"]
        assert container.confluence.params().global_.window_bars == 9
        container.confluence.params().global_.window_bars = 6  # restore for other tests

    def test_history_and_state_filter(self, client, market):
        test_client, container = client
        container.confluence.analyse(market, fx.bullish_stack(market.candles[-1].time))
        history = test_client.get("/api/confluence/history?limit=5").json()
        assert history["count"] >= 1
        assert history["confluences"][0]["id"].startswith("cf_")

        state = container.confluence.tracked()[0].state
        filtered = test_client.get(f"/api/confluence?state={state}").json()
        assert all(group["state"] == state for group in filtered["confluences"])


class TestStreamSnapshot:
    def test_snapshot_is_none_when_nothing_is_tracked(self, monkeypatch, tmp_path):
        from app.api import stream

        container = Container.build()
        container.confluence = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()),
            bus=container.bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
        )
        assert stream._confluence_snapshot(container, "EURUSD", "M15") is None

    def test_snapshot_carries_the_state_for_a_reconnecting_dashboard(self, monkeypatch, tmp_path, market):
        from app.api import stream

        container = Container.build()
        container.confluence = ConfluenceService(
            engine=ConfluenceEngine(ConfluenceParams()),
            bus=container.bus,
            repository=ConfluenceRepository(session_factory=_session_factory(tmp_path)),
        )
        container.confluence.analyse(market, fx.bullish_stack(market.candles[-1].time))
        snapshot = stream._confluence_snapshot(container, "EURUSD", "M15")
        assert snapshot is not None
        assert snapshot.event_type is EventType.CONFLUENCE_SNAPSHOT
        assert snapshot.metadata["confluences"]
        assert snapshot.metadata["trading_signal"] is False
        assert snapshot.metadata["overview"]["max_score"] == 10.0


def _session_factory(tmp_path):
    """A throwaway SQLite database with the real session configuration."""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path/'confluence.db'}", future=True)
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
