"""Phase 3 - price-action end-to-end: API, real-time, persistence, dashboard data.

A detection produced by the price-action engine must be readable through the API,
published on the **same** event bus as Phase 1/2 (WebSocket + SSE), stored in
SQLite with its whole lifecycle, and drawable from real candle coordinates.

Two things are checked everywhere in this file:

* nothing here is a trading instruction (no BUY/SELL/ENTRY/SL/TP anywhere);
* nothing here is invented (no price, no volume, no detection without a rule).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.schemas.events import DetectionStatus, EventType
from tests import price_action_fixtures as fx

FORBIDDEN = ("BUY", "SELL", "ENTRY", "STOP LOSS", "TAKE PROFIT", " TP ", " SL ", "SIGNAL D'ACHAT", "SIGNAL DE VENTE")


def analyse(container, series, *, chartist=None, publish: bool = True):
    return container.price_action.analyse(series, chartist=chartist, publish=publish)


def busy_series():
    """A series that produces several price-action families at once."""
    return fx.bullish_engulfing()


def detection_of(container, pattern: str):
    for detection in container.price_action.tracked():
        if detection.pattern == pattern:
            return detection
    raise AssertionError(
        f"{pattern} not tracked (tracked: {[d.pattern for d in container.price_action.tracked()]})"
    )


def events_of(container, event_type: str) -> list:
    return [event for event in container.bus.history(500) if event.event_type == event_type]


class TestPriceActionApi:
    def test_the_routes_are_documented(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for route in (
            "/api/price-action",
            "/api/price-action/active",
            "/api/price-action/structure",
            "/api/price-action/history",
            "/api/price-action/confluence",
            "/api/price-action/params",
            "/api/price-action/{detection_id}",
        ):
            assert route in paths, f"{route} is not documented: the router was not included"

    def test_empty_state_is_explicit(self, client):
        payload = client.get("/api/price-action").json()
        assert payload["status"] == "NO ACTIVE PRICE ACTION"
        assert payload["detections"] == []
        assert payload["engines"]["PRICE_ACTION_ENGINE"] == "ENABLED"
        assert payload["engines"]["SMC_ICT_ENGINE"] == "ENABLED"

    def test_a_detection_reaches_the_api_with_its_measurements(self, client, container):
        analyse(container, busy_series())
        payload = client.get("/api/price-action").json()
        assert payload["status"] == "ACTIVE PRICE ACTION"
        assert payload["counts"]["DETECTED"] >= 1
        detection = next(item for item in payload["detections"] if item["pattern"] == "BULLISH_ENGULFING")
        assert detection["category"] == "PRICE_ACTION"
        assert detection["source_engine"] == "PRICE_ACTION_ENGINE"
        assert detection["confidence"] > 0
        assert detection["confidence_factors"], "the criteria must travel with the detection"
        assert detection["evidence"], "the human-readable evidence must travel too"
        measurements = detection["evidence_points"]["measurements"]
        assert measurements["coverage_ratio"] >= 1.0
        assert "atr" in measurements
        assert detection["parameters"]["min_coverage"] >= 1.0
        assert detection["parameters"]["engine"]["scan_bars"] > 0

    def test_the_dashboard_has_everything_it_shows(self, client, container):
        """Pattern, symbol, timeframe, direction, timestamp, status, criteria count."""
        analyse(container, busy_series())
        detection = next(
            item for item in client.get("/api/price-action").json()["detections"] if item["pattern"] == "BULLISH_ENGULFING"
        )
        assert detection["pattern"]
        assert detection["symbol"] == "EURUSD"
        assert detection["timeframe"] == "M15"
        assert detection["direction"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert detection["status"] == "DETECTED"
        assert isinstance(detection["detected_at_bar_time"], int)
        validated = sum(1 for factor in detection["confidence_factors"] if factor["passed"])
        assert validated >= 1
        assert len(detection["confidence_factors"]) >= validated
        assert detection["drawing"]["markers"], "a price-action detection must be drawable"
        assert detection["coordinates"], "real coordinates are required for the chart"
        assert detection["evidence_points"]["candle_measurements_available"] == [
            "body_size",
            "upper_wick",
            "lower_wick",
            "range",
            "body_ratio",
            "wick_ratios",
        ]

    def test_no_trading_instruction_anywhere(self, client, container):
        analyse(container, busy_series())
        payload = client.get("/api/price-action").json()
        text = json.dumps(payload).upper()
        for word in FORBIDDEN:
            assert word not in text, f"'{word}' must never appear in a price-action payload"
        assert "TRADING_SIGNAL" in text  # the only mention is the explicit False
        for detection in payload["detections"]:
            assert detection["evidence_points"]["level_context"]["trading_signal"] is False

    def test_active_and_structure_filters(self, client, container):
        analyse(container, fx.consolidation())
        active = client.get("/api/price-action/active").json()
        assert all(item["status"] == "DETECTED" for item in active["detections"])
        structure = client.get("/api/price-action/structure").json()
        assert [item["pattern"] for item in structure["detections"]] == ["CONSOLIDATION"]
        # everything else is not a state and must not appear there
        analyse(container, fx.bullish_engulfing())
        structure = client.get("/api/price-action/structure").json()
        assert all(item["pattern"] in ("IMPULSION", "CONSOLIDATION") for item in structure["detections"])

    def test_symbol_and_timeframe_filters(self, client, container):
        analyse(container, busy_series())
        assert client.get("/api/price-action?symbol=EURUSD&timeframe=M15").json()["detections"]
        assert client.get("/api/price-action?symbol=USDJPY").json()["detections"] == []
        assert client.get("/api/price-action?timeframe=H4").json()["detections"] == []

    def test_detection_detail_and_404(self, client, container):
        analyse(container, busy_series())
        detection = detection_of(container, "BULLISH_ENGULFING")
        detail = client.get(f"/api/price-action/{detection.id}").json()
        assert detail["id"] == detection.id
        assert detail["evidence_points"]["measurements"]["coverage_ratio"] >= 1.0
        assert client.get("/api/price-action/pa_does_not_exist").status_code == 404

    def test_the_scanner_engines_map_is_the_truth(self, client):
        payload = client.get("/api/detections").json()
        assert payload["engines"]["PRICE_ACTION_ENGINE"] == "ENABLED"


class TestCoordinatesOnRealCandles:
    def test_every_coordinate_comes_from_a_real_candle(self, container):
        series = busy_series()
        analyse(container, series)
        by_time = {candle.time: candle for candle in series.candles}
        checked = 0
        for detection in container.price_action.tracked():
            for coordinate in detection.coordinates:
                assert coordinate.time in by_time, "a coordinate must sit on a real bar"
                candle = by_time[coordinate.time]
                assert candle.low - 1e-9 <= coordinate.price <= candle.high + 1e-9, (
                    f"{detection.pattern}: price {coordinate.price} outside the real candle "
                    f"[{candle.low}, {candle.high}]"
                )
                checked += 1
        assert checked >= 2

    def test_zones_and_markers_use_real_bars(self, container):
        series = busy_series()
        analyse(container, series)
        times = {candle.time for candle in series.candles}
        for detection in container.price_action.tracked():
            for zone in detection.drawing.zones:
                assert zone.time_start in times and zone.time_end in times
                assert zone.price_top >= zone.price_bottom
            for marker in detection.drawing.markers:
                assert marker.time in times
        assert True

    def test_measurements_match_the_candles_they_quote(self, container):
        series = busy_series()
        analyse(container, series)
        by_time = {candle.time: candle for candle in series.candles}
        detection = detection_of(container, "BULLISH_ENGULFING")
        for key in ("previous_candle", "current_candle"):
            quoted = detection.evidence_points[key]
            real = by_time[quoted["time"]]
            assert quoted["open"] == real.open
            assert quoted["high"] == real.high
            assert quoted["low"] == real.low
            assert quoted["close"] == real.close


class TestRealTimeDelivery:
    def test_websocket_receives_the_price_action_event(self, client, container):
        with client.websocket_connect("/api/stream?symbol=EURUSD") as websocket:
            hello = json.loads(websocket.receive_text())
            assert hello["event_type"] == "STREAM_HELLO"
            analyse(container, busy_series())
            message = None
            for _ in range(12):  # snapshots / other events may interleave
                candidate = json.loads(websocket.receive_text())
                if candidate["event_type"] == "PRICE_ACTION_DETECTED":
                    message = candidate
                    break
            assert message is not None, "the price-action detection must be pushed live"
            assert message["source"] == "PRICE_ACTION_ENGINE"
            assert message["metadata"]["category"] == "PRICE_ACTION"
            assert message["metadata"]["trading_signal"] is False
            assert message["metadata"]["detection"]["coordinates"]

    def test_reconnecting_dashboard_receives_the_snapshot(self, client, container):
        analyse(container, busy_series())
        with client.websocket_connect("/api/stream?symbol=EURUSD&timeframe=M15") as websocket:
            hello = json.loads(websocket.receive_text())
            assert hello["event_type"] == "STREAM_HELLO"
            snapshot = json.loads(websocket.receive_text())
            assert snapshot["event_type"] == "PRICE_ACTION_SNAPSHOT"
            assert snapshot["metadata"]["trading_signal"] is False
            patterns = [item["pattern"] for item in snapshot["metadata"]["detections"]]
            assert "BULLISH_ENGULFING" in patterns
            assert snapshot["metadata"]["engines"]["PRICE_ACTION_ENGINE"] == "ENABLED"

    @pytest.mark.asyncio
    async def test_sse_receives_the_price_action_event(self, container):
        from app.api.stream import sse_stream

        response = await sse_stream(symbol="EURUSD", timeframe=None, container=container)
        iterator = response.body_iterator
        await asyncio.wait_for(iterator.__anext__(), timeout=2)  # hello
        analyse(container, busy_series())
        payload = None
        for _ in range(12):
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
            if "PRICE_ACTION_DETECTED" not in chunk:
                continue
            payload = json.loads(chunk.split("data: ", 1)[1].strip())
            break
        assert payload is not None, "the SSE stream must deliver the price-action event"
        assert payload["metadata"]["pattern"]
        await iterator.aclose()

    def test_lifecycle_events_are_published_in_order(self, container):
        series = busy_series()
        analyse(container, series)
        detection = detection_of(container, "BULLISH_ENGULFING")
        trigger = detection.confirmation.level
        later = series.model_copy(
            update={
                "candles": series.candles
                + [
                    fx.BarSpec(
                        open=(trigger - fx.BASE) / fx.PIP,
                        high=(trigger - fx.BASE) / fx.PIP + 4.0,
                        low=(trigger - fx.BASE) / fx.PIP - 0.5,
                        close=(trigger - fx.BASE) / fx.PIP + 3.0,
                    ).build(len(series.candles))
                ]
            }
        )
        analyse(container, later)
        events = events_of(container, "PRICE_ACTION_CONFIRMED")
        assert events, "a close beyond the trigger must confirm the pattern"
        detection = detection_of(container, "BULLISH_ENGULFING")
        assert detection.status is DetectionStatus.CONFIRMED
        assert detection.confirmation.confirmed is True
        assert detection.evidence_points["lifecycle"]["anchor_candle_time"] == detection.detected_at_bar_time
        assert any("Confirmation par cloture" == f.criterion for f in detection.confidence_factors), (
            "the confirmation must be an explicit criterion, not a bonus"
        )

    def test_expiry_is_reported(self, container):
        series = busy_series()
        analyse(container, series)
        calm = [
            fx.BarSpec(open=1.0, high=1.4, low=0.8, close=1.2).build(len(series.candles) + offset)
            for offset in range(20)
        ]
        analyse(container, series.model_copy(update={"candles": series.candles + calm}))
        assert any(event.metadata["pattern"] == "BULLISH_ENGULFING" for event in events_of(container, "PRICE_ACTION_EXPIRED")) or (
            detection_of(container, "BULLISH_ENGULFING").status is DetectionStatus.EXPIRED
        )


class TestPersistence:
    def test_detections_are_stored_with_their_measurements(self, container):
        analyse(container, busy_series())
        stored = container.detections_repo.history(limit=10)
        assert stored, "a detection must be persisted"
        row = next(item for item in stored if item["pattern"] == "BULLISH_ENGULFING")
        assert row["category"] == "PRICE_ACTION"
        assert row["source_engine"] == "PRICE_ACTION_ENGINE"
        for key in ("parameters", "confidence_factors", "evidence", "coordinates", "watch_levels", "evidence_points"):
            assert key in row, f"{key} missing from the stored row"
        assert row["evidence_points"]["measurements"]["coverage_ratio"] >= 1.0
        assert row["parameters"]["engine"]["scan_bars"] > 0

    def test_storage_is_the_source_of_truth_after_a_restart(self, container):
        analyse(container, busy_series())
        from app.db.repository import DetectionRepository

        reopened = DetectionRepository()
        assert any(row["pattern"] == "BULLISH_ENGULFING" for row in reopened.history(limit=5))

    def test_history_endpoint_filters(self, client, container):
        analyse(container, busy_series())
        payload = client.get("/api/price-action/history?pattern=BULLISH_ENGULFING").json()
        assert payload["count"] >= 1
        assert all(item["pattern"] == "BULLISH_ENGULFING" for item in payload["detections"])
        empty = client.get("/api/price-action/history?pattern=NOT_A_PATTERN").json()
        assert empty["count"] == 0

    def test_nothing_is_stored_without_an_analysis(self, container):
        assert container.detections_repo.count() == 0
        assert container.detections_repo.history(limit=10) == []


class TestParameters:
    def test_params_are_readable_and_complete(self, client):
        params = client.get("/api/price-action/params").json()["params"]
        for group in (
            "globals",
            "engulfing",
            "pin_bar",
            "hammer",
            "inside_bar",
            "outside_bar",
            "doji",
            "structure",
            "levels",
            "confluence",
            "weights",
        ):
            assert group in params, f"missing parameter group {group}"
        assert params["confluence"]["trading_signal"] is False
        assert params["globals"]["scan_bars"] > 0

    def test_an_override_changes_the_behaviour(self, client, container):
        assert analyse(container, busy_series()).detections
        response = client.patch(
            "/api/price-action/params", json={"overrides": {"globals": {"min_bars_required": 500}}}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "UPDATED"
        container.price_action.engine.clear()
        assert analyse(container, busy_series()).detections == []
        container.price_action.engine.params.globals.min_bars_required = 60  # restore for other tests

    def test_unknown_group_and_parameter_are_refused(self, client):
        assert client.patch("/api/price-action/params", json={"overrides": {"nope": {}}}).status_code == 400
        assert (
            client.patch("/api/price-action/params", json={"overrides": {"engulfing": {"nope": 1}}}).status_code
            == 400
        )

    def test_out_of_bounds_values_are_refused(self, client):
        assert (
            client.patch("/api/price-action/params", json={"overrides": {"globals": {"scan_bars": 0}}}).status_code
            == 422
        )
        assert (
            client.patch("/api/price-action/params", json={"overrides": {"doji": {"max_body_ratio": 2.0}}}).status_code
            == 422
        )

    def test_every_detection_carries_the_parameters_it_used(self, client, container):
        analyse(container, busy_series())
        detection = detection_of(container, "BULLISH_ENGULFING")
        assert detection.evidence_points["parameters_version"]
        assert detection.parameters["parameters_version"] == detection.evidence_points["parameters_version"]
        assert detection.parameters["min_coverage"] >= 1.0

    def test_the_engine_is_deterministic(self, container):
        """Same parameters + same bars = same detections, byte for byte."""
        first = analyse(container, busy_series(), publish=False)
        first_ids = [(d.id, d.pattern, d.confidence) for d in first.detections]
        from app.price_action.engine import PriceActionEngine
        from app.price_action.params import PriceActionParams

        fresh = PriceActionEngine(PriceActionParams())
        second = fresh.analyse(busy_series())
        second_ids = [(d.id, d.pattern, d.confidence) for d in second.detections]
        assert first_ids == second_ids


class TestScannerIntegration:
    @pytest.mark.asyncio
    async def test_the_scanner_runs_the_price_action_engine(self, container, provider):
        provider.candles = busy_series().candles
        await container.scanner.tick()
        assert container.price_action.runs >= 1
        assert container.price_action.bars_analysed > 0
        assert container.price_action.last_run_ms is not None

    @pytest.mark.asyncio
    async def test_the_scanner_only_uses_closed_candles(self, container, provider):
        provider.candles = busy_series().candles
        await container.scanner.tick()
        last_closed = provider.candles[-1].time
        for detection in container.price_action.tracked():
            assert detection.detected_at_bar_time is not None
            assert detection.detected_at_bar_time <= last_closed

    @pytest.mark.asyncio
    async def test_the_price_action_engine_consumes_the_chartist_state(self, container, provider):
        """The scanner hands the chartist detections to the price-action engine:
        no second level engine, no second breakout engine."""
        provider.candles = busy_series().candles
        await container.scanner.tick()
        snapshot = container.price_action.last_results
        assert snapshot, "the last run must be reported"
        for entry in snapshot.values():
            assert "levels_available" in entry["context"]
            assert "breakouts_available" in entry["context"]

    @pytest.mark.asyncio
    async def test_a_short_series_is_not_analysed(self, container, provider):
        provider.candles = busy_series().candles[:40]
        await container.scanner.tick()
        assert container.price_action.runs == 0

    @pytest.mark.asyncio
    async def test_one_run_per_closed_bar(self, container, provider):
        provider.candles = busy_series().candles
        await container.scanner.tick()
        runs = container.price_action.runs
        await container.scanner.tick()  # same bar: no new closed candle
        assert container.price_action.runs == runs


class TestConfluenceEndpoint:
    def test_groups_are_informative_only(self, client, container):
        analyse(container, fx.consolidation())
        payload = client.get("/api/price-action/confluence").json()
        assert payload["trading_signal"] is False
        assert payload["groups"], "the confluence view must report the current state"
        group = payload["groups"][0]
        assert set(group["groups"]) == {"chartist", "price_action", "structure"}
        assert group["groups"]["structure"], "the measured state must appear here"
        text = json.dumps(payload).upper()
        for word in ("BUY", "SELL", "ENTRY"):
            assert word not in text
