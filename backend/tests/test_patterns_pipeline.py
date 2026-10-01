"""Chartist engine - API, real-time delivery, persistence and scanner wiring.

This is the end-to-end side of Phase 2: a detection produced by the engine must
be published on the event bus (WebSocket / SSE), stored in SQLite with its whole
lifecycle, and readable through the API - without ever inventing a price, a
volume or a detection.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.schemas.events import DetectionStatus, EventType, MarketEvent
from app.schemas.market import Timeframe
from tests.pattern_fixtures import build_series, double_bottom, double_top


def analyse(container, scenario, *, publish: bool = True):
    return container.patterns.analyse(scenario.series, publish=publish)


def events_of(container, event_type: str) -> list:
    return [event for event in container.bus.history(500) if event.event_type == event_type]


def detection_of(container, pattern: str):
    for detection in container.patterns.tracked():
        if detection.pattern == pattern:
            return detection
    raise AssertionError(f"{pattern} not tracked (tracked: {[d.pattern for d in container.patterns.tracked()]})")


class TestDetectionApi:
    def test_the_detection_routes_are_documented(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for route in (
            "/api/detections",
            "/api/detections/active",
            "/api/detections/history",
            "/api/detections/{detection_id}",
            "/api/patterns/params",
        ):
            assert route in paths, f"{route} is not documented: the router was not included"

    def test_no_detection_is_reported_before_any_analysis(self, client):
        payload = client.get("/api/detections").json()
        assert payload["status"] == "NO ACTIVE DETECTION"
        assert payload["detections"] == []
        assert payload["engines"]["CHART_PATTERN_ENGINE"] == "ENABLED"
        # Phase 3: the price-action engine is live (its own endpoint is
        # /api/price-action), SMC/ICT remains out of scope
        assert payload["engines"]["PRICE_ACTION_ENGINE"] == "ENABLED"
        assert payload["engines"]["SMC_ICT_ENGINE"] == "ENABLED"

    def test_a_real_detection_reaches_the_api_with_its_evidence(self, client, container):
        analyse(container, double_top())
        payload = client.get("/api/detections").json()
        assert payload["status"] == "ACTIVE DETECTIONS"
        assert payload["counts"]["DETECTED"] >= 1
        detection = next(item for item in payload["detections"] if item["pattern"] == "DOUBLE_TOP")
        assert detection["symbol"] == "EURUSD"
        assert detection["category"] == "CHARTISTE"
        assert detection["pattern"] == "DOUBLE_TOP"
        assert detection["direction"] == "BEARISH"
        assert detection["status"] == "DETECTED"
        assert detection["confidence"] > 0
        assert detection["evidence"], "the API must expose the why of the detection"
        assert detection["evidence_points"]["neckline"]["price"] > 0
        assert detection["coordinates"], "the API must expose drawable coordinates"
        assert detection["parameters"]["peak_tolerance_pips"] > 0
        assert detection["confirmation"]["confirmed"] is False

    def test_the_active_filter_only_returns_unconfirmed_formations(self, client, container):
        status = analyse(container, double_top(breakout=True)).detections
        assert any(d.status is DetectionStatus.CONFIRMED for d in status)
        active = client.get("/api/detections/active").json()
        assert all(item["status"] == "DETECTED" for item in active["detections"])
        assert not any(item["pattern"] == "DOUBLE_TOP" for item in active["detections"])

    def test_symbol_and_timeframe_filters(self, client, container):
        analyse(container, double_top())
        assert client.get("/api/detections?symbol=EURUSD").json()["detections"]
        assert client.get("/api/detections?symbol=USDJPY").json()["detections"] == []
        assert client.get("/api/detections?timeframe=M15").json()["detections"]
        assert client.get("/api/detections?timeframe=H4").json()["detections"] == []

    def test_a_single_detection_is_readable_by_id(self, client, container):
        analyse(container, double_bottom())
        listed = client.get("/api/detections").json()["detections"][0]
        detail = client.get(f"/api/detections/{listed['id']}").json()
        assert detail["id"] == listed["id"]
        assert detail["pattern"] == "DOUBLE_BOTTOM"
        assert client.get("/api/detections/ct_does_not_exist").status_code == 404

    def test_history_endpoint_exposes_the_stored_lifecycle(self, client, container):
        analyse(container, double_top(breakout=True))
        history = client.get("/api/detections/history").json()
        assert history["count"] >= 1
        row = next(item for item in history["detections"] if item["pattern"] == "DOUBLE_TOP")
        assert row["status"] == "CONFIRMED"
        assert row["breakout"]["level"] > 0
        filtered = client.get("/api/detections/history?pattern=DOUBLE_TOP").json()
        assert filtered["count"] == 1
        assert filtered["detections"][0]["pattern"] == "DOUBLE_TOP"
        assert client.get("/api/detections/history?pattern=CHANNEL").json()["count"] == 0
        confirmed = client.get("/api/detections/history?status=CONFIRMED").json()
        assert confirmed["count"] == 1

    def test_history_rejects_an_absurd_limit(self, client):
        assert client.get("/api/detections/history?limit=0").status_code == 422
        assert client.get("/api/detections/history?limit=5000").status_code == 422

    def test_parameters_are_centralised_and_readable(self, client):
        payload = client.get("/api/patterns/params").json()
        params = payload["params"]
        assert params["globals"]["window_bars"] > 0
        assert params["globals"]["min_bars_required"] >= 1
        assert params["double_top_bottom"]["peak_tolerance_pips"] > 0
        assert params["head_shoulders"]["require_trend_context"] is True
        assert params["triangle"]["min_touches_per_line"] >= 3
        assert params["wedge"]["min_touches_per_line"] >= 3
        assert params["rectangle"]["min_touches_per_side"] >= 2
        assert params["flags"]["impulse_min_atr"] > 0
        assert params["breakout"]["buffer_pips"] > 0
        assert payload["engines"]["CHART_PATTERN_ENGINE"] == "ENABLED"

    def test_parameters_can_be_overridden_at_runtime_and_are_validated(self, client, container):
        response = client.patch(
            "/api/patterns/params", json={"overrides": {"double_top_bottom": {"peak_tolerance_pips": 3.0}}}
        )
        assert response.status_code == 200
        assert response.json()["params"]["double_top_bottom"]["peak_tolerance_pips"] == 3.0
        assert container.patterns.params.double_top_bottom.peak_tolerance_pips == 3.0
        assert client.patch("/api/patterns/params", json={"overrides": {"nope": {"x": 1}}}).status_code == 400
        assert client.patch(
            "/api/patterns/params", json={"overrides": {"double_top_bottom": {"peak_tolerance_pips": "abc"}}}
        ).status_code == 422
        assert client.patch(
            "/api/patterns/params", json={"overrides": {"globals": {"window_bars": -5}}}
        ).status_code == 422


class TestRealtimeDelivery:
    def test_pattern_events_are_published_on_the_bus(self, container):
        analyse(container, double_top(breakout=True))
        types = [event.event_type.value for event in container.bus.history(500)]
        assert "PATTERN_DETECTED" in types
        assert "BREAKOUT_DETECTED" in types
        assert "PATTERN_CONFIRMED" in types
        assert types.index("PATTERN_DETECTED") < types.index("PATTERN_CONFIRMED")

    def test_the_event_payload_carries_the_whole_detection(self, container):
        analyse(container, double_top(breakout=True))
        event = events_of(container, "PATTERN_CONFIRMED")[-1]
        assert event.symbol == "EURUSD"
        assert event.source == "CHART_PATTERN_ENGINE"
        detection = event.metadata["detection"]
        assert detection["pattern"] == "DOUBLE_TOP"
        assert detection["evidence_points"]["valley"]["price"] > 0
        assert detection["drawing"]["levels"]
        assert detection["breakout"]["level"] > 0, "the confirmation must carry the broken level"
        assert event.metadata["provider"] == "fixture"
        assert detection["confirmation"]["volume"] is None

    def test_no_event_is_re_emitted_for_an_unchanged_formation(self, container):
        analyse(container, double_top())
        first = events_of(container, "PATTERN_DETECTED")
        patterns = [event.metadata["pattern"] for event in first]
        assert len(patterns) == len(set(patterns)), "one announcement per formation"
        analyse(container, double_top())
        assert len(events_of(container, "PATTERN_DETECTED")) == len(first)

    def test_the_websocket_receives_the_detection_without_a_reload(self, client, container):
        with client.websocket_connect("/api/stream?symbol=EURUSD") as websocket:
            hello = json.loads(websocket.receive_text())
            assert hello["event_type"] == "STREAM_HELLO"
            analyse(container, double_top())
            message = None
            for _ in range(10):  # other symbols / heartbeats may interleave
                candidate = json.loads(websocket.receive_text())
                if candidate["event_type"] == "PATTERN_DETECTED":
                    message = candidate
                    break
            assert message is not None, "the detection must be pushed without any reload"
            assert message["metadata"]["detection"]["pattern"] == "DOUBLE_TOP"
            assert message["metadata"]["detection"]["coordinates"]
            assert message["source"] == "CHART_PATTERN_ENGINE"

    @pytest.mark.asyncio
    async def test_the_sse_stream_receives_the_detection(self, container):
        from app.api.stream import sse_stream

        response = await sse_stream(symbol="EURUSD", timeframe=None, container=container)
        iterator = response.body_iterator
        await asyncio.wait_for(iterator.__anext__(), timeout=2)  # hello
        # the current state is sent right after the hello (Phase 2/3 snapshots):
        # those chunks are skipped until the real lifecycle event arrives
        analyse(container, double_bottom())
        payload = None
        for _ in range(10):
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
            if "PATTERN_DETECTED" not in chunk:
                continue
            payload = json.loads(chunk.split("data: ", 1)[1].strip())
            break
        assert payload is not None, "the SSE stream must deliver the detection"
        assert payload["metadata"]["detection"]["pattern"] == "DOUBLE_BOTTOM"
        await iterator.aclose()

    def test_a_reconnecting_client_receives_the_current_state(self, client, container):
        """The snapshot is sent to the new connection only: no reload, no wait."""
        analyse(container, double_top())
        with client.websocket_connect("/api/stream?symbol=EURUSD&timeframe=M15") as websocket:
            hello = json.loads(websocket.receive_text())
            assert hello["event_type"] == "STREAM_HELLO"
            snapshot = json.loads(websocket.receive_text())
            assert snapshot["event_type"] == "DETECTIONS_SNAPSHOT"
            patterns = [item["pattern"] for item in snapshot["metadata"]["detections"]]
            assert "DOUBLE_TOP" in patterns
            assert snapshot["metadata"]["engines"]["CHART_PATTERN_ENGINE"] == "ENABLED"

    def test_no_snapshot_is_sent_when_nothing_is_tracked(self, client, container):
        with client.websocket_connect("/api/stream?symbol=EURUSD&timeframe=M15") as websocket:
            assert json.loads(websocket.receive_text())["event_type"] == "STREAM_HELLO"
            container.bus.publish_nowait(
                MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.1)
            )
            message = json.loads(websocket.receive_text())
            assert message["event_type"] == "MARKET_UPDATE", "no empty snapshot must be invented"

    def test_the_snapshot_is_filtered_on_the_requested_series(self, client, container):
        analyse(container, double_top())
        with client.websocket_connect("/api/stream?symbol=USDJPY&timeframe=M15") as websocket:
            assert json.loads(websocket.receive_text())["event_type"] == "STREAM_HELLO"
            container.bus.publish_nowait(
                MarketEvent(event_type=EventType.SYSTEM_STATUS, metadata={"heartbeat": True})
            )
            message = json.loads(websocket.receive_text())
            assert message["event_type"] == "SYSTEM_STATUS", (
                "a USDJPY subscriber must not receive an EURUSD snapshot"
            )

    def test_an_engine_error_is_reported_and_never_hidden(self, container):
        broken = double_top().series

        class Boom(Exception):
            pass

        original = container.patterns.engine.analyse

        def explode(*args, **kwargs):
            raise Boom("detector crash (test)")

        container.patterns.engine.analyse = explode
        try:
            result = container.patterns.analyse(broken)
        finally:
            container.patterns.engine.analyse = original
        assert result.detections == []
        assert any("Boom" in note for note in result.notes)
        assert container.patterns.errors, "the failure must stay visible in the service state"


class TestPersistence:
    def test_a_detection_is_stored_with_its_full_lifecycle(self, container):
        analyse(container, double_top(breakout=True))
        rows = container.detections_repo.history(limit=10)
        assert rows, "the detection must be persisted"
        row = next(item for item in rows if item["pattern"] == "DOUBLE_TOP")
        assert row["status"] == "CONFIRMED"
        assert row["symbol"] == "EURUSD"
        assert row["timeframe"] == "M15"
        assert row["category"] == "CHARTISTE"
        assert row["dedup_key"].startswith("ct_")
        assert row["confidence"] > 0
        assert row["evidence_points"]["neckline"]["price"] > 0
        assert row["drawing"]["levels"]
        assert row["breakout"]["level"] > 0
        assert row["detected_at_bar_time"] is not None

    def test_one_row_per_formation_across_its_whole_life(self, container):
        formation = double_top().series
        container.patterns.analyse(formation)
        rows = container.detections_repo.count()
        container.patterns.analyse(formation)
        assert container.detections_repo.count() == rows, "a stable formation keeps its single row"
        container.patterns.analyse(double_top(breakout=True).series)
        assert container.detections_repo.count() == rows, "the lifecycle must update the same row"
        stored = next(row for row in container.detections_repo.history(limit=10) if row["pattern"] == "DOUBLE_TOP")
        assert stored["status"] == "CONFIRMED"

    def test_history_survives_a_fresh_engine_and_service(self, container):
        analyse(container, double_bottom())
        stored = container.detections_repo.history(limit=5)
        assert stored
        # a new service (fresh in-memory registry) still reads the history: the
        # storage - not the process memory - is the source of truth
        from app.db.repository import DetectionRepository

        reopened = DetectionRepository()
        assert any(row["pattern"] == "DOUBLE_BOTTOM" for row in reopened.history(limit=5))

    def test_a_detection_is_never_stored_without_analysis(self, container):
        assert container.detections_repo.count() == 0
        assert container.detections_repo.history(limit=10) == []

    def test_stored_rows_carry_everything_needed_for_backtesting(self, container):
        analyse(container, double_top(breakout=True, retest=True))
        row = next(item for item in container.detections_repo.history(limit=5) if item["pattern"] == "DOUBLE_TOP")
        for key in (
            "parameters",
            "confidence_factors",
            "evidence",
            "coordinates",
            "confirmation",
            "invalidation",
            "watch_levels",
            "bars_in_window",
        ):
            assert key in row, f"{key} missing from the stored row"
        assert row["parameters"]["peak_tolerance_pips"] > 0
        assert row["parameters"]["atr"] > 0


class TestScannerIntegration:
    @pytest.mark.asyncio
    async def test_the_scanner_runs_the_engine_once_per_new_closed_bar(self, container, provider):
        provider.candles = double_top().series.candles
        await container.scanner.tick()
        first_runs = container.patterns.runs
        assert first_runs >= 1, "the first observation must trigger an analysis"
        await container.scanner.tick()  # same bar: no recomputation
        assert container.patterns.runs == first_runs

    @pytest.mark.asyncio
    async def test_the_scanner_never_analyses_open_candles(self, container, provider):
        candles = double_top().series.candles
        provider.candles = candles
        await container.scanner.tick()
        for detection in container.patterns.tracked():
            assert detection.detected_at_bar_time is not None
            assert detection.detected_at_bar_time <= candles[-1].time

    @pytest.mark.asyncio
    async def test_a_short_series_is_not_analysed(self, container, provider):
        provider.candles = build_series([1.1000, 1.1010, 1.0990, 1.1005], bars_per_leg=10).candles
        await container.scanner.tick()
        assert container.patterns.runs == 0
        assert container.detections_repo.count() == 0

    @pytest.mark.asyncio
    async def test_analysis_does_not_block_the_scan(self, container, provider):
        provider.candles = double_top().series.candles
        await container.scanner.tick()
        last = container.runs_repo.last()
        assert last is not None and last["finished_at"] is not None
        assert container.patterns.last_run_ms is not None
        assert container.patterns.last_run_ms < 1000, "one series must stay fast enough for the scanner"
