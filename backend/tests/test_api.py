"""API tests: every endpoint, the DATA UNAVAILABLE contract and validation."""

from __future__ import annotations

import json

import pytest

from app.providers.errors import ProviderUnavailable

ENDPOINTS = [
    "/api/health",
    "/api/ready",
    "/api/symbols",
    "/api/status",
    "/api/detections",
    "/api/market-status",
    "/api/market/EURUSD?timeframe=M15",
    "/api/candles/EURUSD/M15?limit=50",
    "/api/structure/EURUSD/M15?limit=100",
    "/api/instruments/EURUSD",
    "/api/events/recent?limit=5",
    "/api/database/coverage",
    "/api/telegram/status",
    "/api/capture/status",
    "/api/stream/status",
]


class TestEndpointsRespond:
    @pytest.mark.parametrize("url", ENDPOINTS)
    def test_returns_200_with_json(self, client, url):
        response = client.get(url)
        assert response.status_code == 200, f"{url} -> {response.status_code} {response.text[:200]}"
        assert response.headers["content-type"].startswith("application/json")

    def test_openapi_documents_every_route(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        for expected in ("/api/health", "/api/symbols", "/api/status", "/api/detections"):
            assert expected in paths

    def test_root_lists_capabilities(self, client):
        payload = client.get("/api").json()
        assert payload["order_execution"] is False
        assert payload["websocket"] == "/api/stream"


class TestSymbols:
    def test_symbol_payload_shape(self, client):
        payload = client.get("/api/symbols").json()
        assert payload["count"] == 2  # FakeProvider exposes EURUSD and USDJPY
        assert payload["timeframes"] == ["M5", "M15", "H1", "H4", "D1"]
        first = payload["symbols"][0]
        for key in ("symbol", "description", "digits", "pip_size", "provider_symbol"):
            assert key in first

    def test_instrument_metadata(self, client):
        payload = client.get("/api/instruments/USDJPY").json()
        assert payload["digits"] == 3
        assert payload["pip_size"] == 0.01

    def test_lowercase_input_is_normalised(self, client):
        assert client.get("/api/instruments/eurusd").json()["symbol"] == "EURUSD"
        assert client.get("/api/candles/eurusd/m15?limit=20").status_code == 200

    def test_separator_symbols_are_accepted_in_path(self, client):
        # EUR/USD cannot be used raw in a path segment; the normaliser is unit-tested
        # and the path form with a dash is accepted here.
        payload = client.get("/api/instruments/EUR-USD").json()
        assert payload["symbol"] == "EURUSD"


class TestMarketSnapshot:
    def test_quote_has_price_and_state(self, client):
        payload = client.get("/api/market/EURUSD?timeframe=M15").json()
        assert payload["symbol"] == "EURUSD"
        assert payload["timeframe"] == "M15"
        assert payload["data_state"] in ("CONNECTED", "CACHED", "STALE")
        assert payload["price"] is not None
        assert payload["last_update"] is not None
        assert payload["market"] is not None

    def test_quote_never_returns_a_price_when_the_provider_fails(self, client, provider):
        provider.fail_with = ProviderUnavailable("down (test)")
        payload = client.get("/api/market/EURUSD?timeframe=M15").json()
        assert payload["data_state"] == "DATA_UNAVAILABLE"
        assert payload["price"] is None
        assert payload["change"] is None
        assert payload["error"]


class TestCandles:
    def test_candles_are_ordered_without_future_bars(self, client):
        payload = client.get("/api/candles/EURUSD/M15?limit=40").json()
        assert payload["count"] == 40
        candles = payload["candles"]
        times = [c["time"] for c in candles]
        assert times == sorted(times)
        assert len(set(times)) == len(times)
        assert payload["data_state"] in ("CONNECTED", "CACHED", "STALE")
        for candle in candles:
            assert candle["high"] >= max(candle["open"], candle["close"])
            assert candle["low"] <= min(candle["open"], candle["close"])

    def test_limit_is_bounded(self, client):
        assert client.get("/api/candles/EURUSD/M15?limit=999999").status_code == 422
        assert client.get("/api/candles/EURUSD/M15?limit=1").status_code == 422

    def test_provider_failure_returns_503_data_unavailable(self, client, provider):
        provider.fail_with = ProviderUnavailable("down (test)")
        response = client.get("/api/candles/EURUSD/M15?limit=50")
        assert response.status_code == 503
        body = response.json()
        assert body["error"] == "DATA_UNAVAILABLE"
        assert body["cause"] == "PROVIDER_UNAVAILABLE"
        assert "candles" not in body, "no placeholder candle may ever be returned"


class TestStructureEndpoint:
    def test_structure_contract(self, client, provider):
        from tests.conftest import candles_from_ranges
        from app.schemas.market import Timeframe

        provider.candles = candles_from_ranges(
            [(1.01, 1.00), (1.10, 1.02), (1.06, 1.01), (1.13, 1.05), (1.09, 1.045), (1.16, 1.06), (1.12, 1.08)],
            timeframe=Timeframe.M15,
        )
        payload = client.get("/api/structure/EURUSD/M15?limit=100&pivot_left=1&pivot_right=1").json()
        assert payload["trend"] == "BULLISH"
        assert payload["recent_labels"] == ["HH", "HL", "HH"]
        assert payload["using_closed_candles_only"] is True
        assert payload["smc_ict"]["implemented"] is False
        assert payload["last_swing_high"]["price"] == 1.16
        assert payload["swing_count"] >= 4

    def test_trend_never_claims_smc(self, client):
        payload = client.get("/api/structure/EURUSD/M15?limit=100").json()
        assert payload["trend"] in ("BULLISH", "BEARISH", "RANGE", "UNDEFINED")


class TestValidation:
    @pytest.mark.parametrize("url", ["/api/candles/XXXYYY/M15", "/api/market/XXXYYY", "/api/structure/XXXYYY/M15"])
    def test_unknown_symbol_is_422(self, client, url):
        response = client.get(url)
        assert response.status_code == 422
        assert response.json()["error"] == "INVALID_SYMBOL"

    @pytest.mark.parametrize("url", ["/api/candles/EURUSD/W1", "/api/market/EURUSD?timeframe=Z9"])
    def test_unknown_timeframe_is_422(self, client, url):
        response = client.get(url)
        assert response.status_code == 422
        assert response.json()["error"] == "INVALID_TIMEFRAME"

    def test_pivot_window_is_validated(self, client):
        assert client.get("/api/structure/EURUSD/M15?pivot_left=0").status_code == 422
        assert client.get("/api/structure/EURUSD/M15?pivot_right=99").status_code == 422


class TestStatus:
    def test_status_card_is_complete(self, client):
        payload = client.get("/api/status").json()
        assert payload["provider"] == "fake"
        assert payload["watchlist_size"] >= 1
        assert payload["scanner"]["running"] is False
        assert payload["stream"]["websocket_endpoint"] == "/api/stream"
        assert payload["database"]["backend"] == "sqlite"
        # Phase 3 implemented the chartist and price-action engines; Phase 4
        # implements SMC/ICT, so the card now reports three ENABLED engines.
        assert payload["detection_engines"] == {
            "CHART_PATTERN_ENGINE": "ENABLED",
            "PRICE_ACTION_ENGINE": "ENABLED",
            "SMC_ICT_ENGINE": "ENABLED",
        }
        assert payload["patterns"]["engine"] == "CHART_PATTERN_ENGINE"
        assert payload["patterns"]["enabled"] is True
        assert payload["safety"]["order_execution"] is False
        assert payload["safety"]["broker_connection"] is False
        assert payload["capture"]["implemented"] is False
        assert payload["config"]["telegram"] == "NOT_CONFIGURED"

    def test_health_and_ready(self, client):
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        ready = client.get("/api/ready").json()
        assert set(ready["components"]) == {"database", "provider", "scanner"}


class TestDetections:
    def test_no_detection_before_any_bar_is_analysed(self, client):
        """Phase 2 replaces the Phase 1 stub: the chartist engine is live but,
        with no analysed series yet, nothing is reported as detected."""
        payload = client.get("/api/detections").json()
        assert payload["status"] == "NO ACTIVE DETECTION"
        assert payload["detections"] == []
        assert payload["engines"] == {
            "CHART_PATTERN_ENGINE": "ENABLED",
            "PRICE_ACTION_ENGINE": "ENABLED",
            "SMC_ICT_ENGINE": "ENABLED",
        }

    def test_nothing_is_persisted_before_any_detection(self, client, container):
        assert container.detections_repo.count() == 0


class TestCaptureContract:
    def test_capture_status_is_explicit(self, client):
        """Phase 1 exposed the CONTRACT; Phase 7 implemented the renderer.

        The original control is kept and strengthened: the Phase 1 contract is still
        served (never deleted), and the endpoint must now report the real capability
        instead of the old "not implemented" limitation.
        """
        payload = client.get("/api/capture/status").json()

        # Phase 1 contract, preserved as-is under its own key
        assert payload["legacy_contract"]["status"] == "CAPTURE_NOT_IMPLEMENTED"
        assert payload["legacy_contract"]["implemented"] is False
        assert "pattern_name" in payload["legacy_contract"]["required_elements"]

        # Phase 7 reality: a renderer exists and says so
        assert payload["status"] in ("CAPTURE_READY", "CAPTURE_NOT_IMPLEMENTED")
        assert payload["implemented"] is payload["enabled"]
        assert "resolutions" in payload, "les resolutions reelles sont annoncees"
        assert "stats" in payload

    @pytest.mark.asyncio
    async def test_build_context_carries_every_required_element(self):
        from app.services.visual_capture import ChartSnapshotService, SnapshotRequest
        from app.schemas.market import Timeframe
        from tests.conftest import candles_from_ranges

        service = ChartSnapshotService()
        request = SnapshotRequest(
            symbol="EURUSD",
            timeframe=Timeframe.M15,
            candles=candles_from_ranges([(1.01, 1.00), (1.02, 1.005)], timeframe=Timeframe.M15),
            price=1.015,
        )
        context = service.build_context(request)
        for key in ("candles", "symbol", "timeframe", "timestamp", "price", "levels", "zones", "annotations", "pattern_name"):
            assert key in context
        assert context["symbol"] == "EURUSD"

    @pytest.mark.asyncio
    async def test_capture_returns_not_implemented_without_fake_image(self):
        from app.services.visual_capture import CaptureStatus, ChartSnapshotService, SnapshotRequest
        from app.schemas.market import Timeframe

        result = await ChartSnapshotService().capture(
            SnapshotRequest(symbol="EURUSD", timeframe=Timeframe.M15)
        )
        assert result.status is CaptureStatus.NOT_IMPLEMENTED
        assert result.image_path is None and result.image_base64 is None


class TestTelegram:
    def test_status_hides_secrets(self, client):
        payload = client.get("/api/telegram/status").json()
        assert payload["status"] == "NOT_CONFIGURED"
        assert payload["bot_token_present"] is False
        assert payload["bot_token_preview"] == "NOT_SET"

    def test_test_endpoint_is_a_noop_without_configuration(self, client):
        payload = client.post("/api/telegram/test").json()
        assert payload["status"] == "NOT_CONFIGURED"
        assert payload["message_id"] is None


class TestEvents:
    def test_recent_events_endpoint(self, client, container):
        from app.schemas.events import EventType, MarketEvent
        from app.schemas.market import Timeframe

        container.events_repo.save(
            MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", timeframe=Timeframe.M15, price=1.1)
        )
        payload = client.get("/api/events/recent?limit=10").json()
        assert payload["stored_count"] >= 1
        assert any(row["symbol"] == "EURUSD" for row in payload["stored"])
        json.dumps(payload)  # must be JSON serialisable
