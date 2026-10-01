"""Real-time tests: WebSocket, SSE, reconnection and scanner event flow."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.schemas.events import EventType, MarketEvent
from app.schemas.market import DataState, Timeframe
from app.services.events import EventBus


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_reaches_every_subscriber(self):
        bus = EventBus()
        _, first = await bus.subscribe()
        _, second = await bus.subscribe()
        event = MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.1)
        bus.publish_nowait(event)
        assert (await first.get()).id == event.id
        assert (await second.get()).id == event.id
        assert bus.subscriber_count == 2
        assert bus.published_total == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        first_id, first = await bus.subscribe()
        await bus.unsubscribe(first_id)
        bus.publish_nowait(MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD"))
        assert first.empty()
        assert bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_slow_subscriber_drops_oldest_event_instead_of_blocking(self):
        bus = EventBus()
        _, queue = await bus.subscribe()
        for i in range(300):
            bus.publish_nowait(MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=float(i)))
        assert queue.qsize() <= 200
        assert bus.published_total == 300

    @pytest.mark.asyncio
    async def test_history_is_bounded(self):
        bus = EventBus(history_size=5)
        for i in range(20):
            bus.publish_nowait(MarketEvent(event_type=EventType.MARKET_UPDATE, price=float(i)))
        assert len(bus.history(100)) == 5


def receive_until(websocket, event_type: str, max_messages: int = 10) -> dict:
    """Read messages until ``event_type`` shows up (heartbeats are skipped)."""
    for _ in range(max_messages):
        message = json.loads(websocket.receive_text())
        if message["event_type"] == event_type:
            return message
    raise AssertionError(f"{event_type} not received")


class TestWebSocketStream:
    def test_hello_then_market_update(self, client: TestClient, container):
        with client.websocket_connect("/api/stream?symbol=EURUSD&timeframe=M15") as websocket:
            hello = json.loads(websocket.receive_text())
            assert hello["event_type"] == "STREAM_HELLO"
            assert hello["metadata"]["provider"] == "fake"
            assert hello["metadata"]["subscriber_id"] >= 1

            container.bus.publish_nowait(
                MarketEvent(
                    event_type=EventType.MARKET_UPDATE,
                    symbol="EURUSD",
                    timeframe=Timeframe.M15,
                    price=1.1234,
                    metadata={"data_state": DataState.CONNECTED.value},
                )
            )
            message = receive_until(websocket, "MARKET_UPDATE")
            assert message["symbol"] == "EURUSD"
            assert message["price"] == 1.1234
            assert message["metadata"]["data_state"] == "CONNECTED"

    def test_symbol_filter_receives_other_pairs_status_only(self, client: TestClient, container):
        with client.websocket_connect("/api/stream?symbol=EURUSD") as websocket:
            json.loads(websocket.receive_text())  # hello
            container.bus.publish_nowait(
                MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="GBPUSD", price=1.3)
            )
            container.bus.publish_nowait(
                MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.1)
            )
            message = receive_until(websocket, "MARKET_UPDATE")
            assert message["symbol"] == "EURUSD", "events of other symbols must be filtered out"

    def test_disconnect_releases_the_subscriber(self, client: TestClient, container):
        with client.websocket_connect("/api/stream") as websocket:
            json.loads(websocket.receive_text())
            assert container.bus.subscriber_count == 1
        assert container.bus.subscriber_count == 0

    def test_reconnection_works(self, client: TestClient, container):
        for attempt in range(2):
            with client.websocket_connect("/api/stream") as websocket:
                hello = json.loads(websocket.receive_text())
                assert hello["event_type"] == "STREAM_HELLO"
                container.bus.publish_nowait(
                    MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.0 + attempt)
                )
                message = receive_until(websocket, "MARKET_UPDATE")
                assert message["price"] == 1.0 + attempt
        assert container.bus.subscriber_count == 0

    def test_stream_status_endpoint_counts_subscribers(self, client: TestClient):
        assert client.get("/api/stream/status").json()["subscribers"] == 0
        assert client.get("/api/stream/status").json()["sse_endpoint"] == "/api/events"


class TestSseStream:
    """SSE is consumed directly from the ASGI generator.

    ``TestClient``/``httpx`` buffer a response until it completes, which never
    happens for an endless event stream, so the endpoint coroutine is driven
    directly here - the real generator logic is still what is exercised.
    """

    @pytest.mark.asyncio
    async def test_sse_sends_hello_then_market_update(self, container):
        from app.api.stream import sse_stream

        response = await sse_stream(symbol="EURUSD", timeframe=None, container=container)
        assert response.media_type == "text/event-stream"
        iterator = response.body_iterator

        hello_chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
        assert hello_chunk.startswith("event: hello")
        payload = json.loads(hello_chunk.split("data: ", 1)[1].strip())
        assert payload["event_type"] == "STREAM_HELLO"

        container.bus.publish_nowait(
            MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.2345)
        )
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
        assert "MARKET_UPDATE" in chunk
        assert "1.2345" in chunk

        await iterator.aclose()
        assert container.bus.subscriber_count == 0, "closing the stream must release the subscriber"

    @pytest.mark.asyncio
    async def test_sse_filters_other_symbols(self, container):
        from app.api.stream import sse_stream

        response = await sse_stream(symbol="USDJPY", timeframe=None, container=container)
        iterator = response.body_iterator
        await asyncio.wait_for(iterator.__anext__(), timeout=2)  # hello

        container.bus.publish_nowait(MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", price=1.0))
        container.bus.publish_nowait(MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="USDJPY", price=157.5))
        chunk = await asyncio.wait_for(iterator.__anext__(), timeout=2)
        payload = json.loads(chunk.split("data: ", 1)[1].strip())
        assert payload["symbol"] == "USDJPY"

        await iterator.aclose()

    @pytest.mark.asyncio
    async def test_sse_heartbeat_when_idle(self, container):
        from app.api.stream import sse_stream

        response = await sse_stream(symbol=None, timeframe=None, container=container)
        iterator = response.body_iterator
        await asyncio.wait_for(iterator.__anext__(), timeout=2)
        with pytest.raises(asyncio.TimeoutError):
            # nothing published: only the periodic heartbeat would arrive
            await asyncio.wait_for(iterator.__anext__(), timeout=0.2)
        await iterator.aclose()

    def test_stream_routes_are_documented(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/events" in paths
        assert "/api/stream/status" in paths


class TestScannerEvents:
    @pytest.mark.asyncio
    async def test_tick_publishes_market_update_with_real_prices(self, container):
        result = await container.scanner.tick()
        assert result["pairs_scanned"] >= 1
        events = [e for e in container.bus.history(100) if e.event_type is EventType.MARKET_UPDATE]
        assert events, "a scanner tick must publish MARKET_UPDATE events"
        for event in events:
            assert event.price is not None
            assert event.timeframe is not None
            assert event.metadata["data_state"] in ("CONNECTED", "CACHED", "STALE")

    @pytest.mark.asyncio
    async def test_tick_reports_provider_failure_without_inventing_prices(self, container, provider):
        from app.providers.errors import ProviderUnavailable

        provider.fail_with = ProviderUnavailable("down (test)")
        result = await container.scanner.tick()
        assert result["pairs_failed"] >= 1
        assert result["errors"]
        statuses = [e for e in container.bus.history(200) if e.event_type is EventType.PROVIDER_STATUS]
        assert statuses
        assert statuses[0].metadata["data_state"] == DataState.DATA_UNAVAILABLE.value
        assert statuses[0].price is None

    @pytest.mark.asyncio
    async def test_second_tick_publishes_candle_closed_for_new_bar(self, container, provider):
        import time as _time

        from tests.conftest import make_candles

        first_bar_open = int(_time.time()) // 900 * 900
        provider.candles = make_candles([1.10 + i * 0.001 for i in range(60)], end_time=first_bar_open)
        await container.scanner.tick()

        # one more closed bar appears -> CANDLE_CLOSED must be published
        provider.candles = make_candles(
            [1.10 + i * 0.001 for i in range(61)], end_time=first_bar_open + 900
        )
        from app.services.cache import series_cache

        series_cache.invalidate()  # inside the TTL the scanner legitimately re-uses the cache
        await container.scanner.tick()
        closed = [e for e in container.bus.history(300) if e.event_type is EventType.CANDLE_CLOSED]
        assert closed, "a newly closed candle must be reported"
        assert closed[-1].metadata["close"] == pytest.approx(closed[-1].price)

    @pytest.mark.asyncio
    async def test_structure_update_is_published_once_per_trend_change(self, container):
        await container.scanner.tick()
        first = [e for e in container.bus.history(400) if e.event_type is EventType.STRUCTURE_UPDATE]
        await container.scanner.tick()
        second = [e for e in container.bus.history(800) if e.event_type is EventType.STRUCTURE_UPDATE]
        assert len(second) == len(first), "an unchanged trend must not republish"

    @pytest.mark.asyncio
    async def test_scanner_records_a_run_row(self, container):
        await container.scanner.tick()
        last = container.runs_repo.last()
        assert last is not None
        assert last["provider"] == "fake"
        assert last["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_no_detection_event_is_ever_published(self, container):
        await container.scanner.tick()
        forbidden = {"PATTERN_DETECTION", "DETECTION", "SIGNAL"}
        assert not any(e.event_type.value in forbidden for e in container.bus.history(500))

    @pytest.mark.asyncio
    async def test_start_and_stop_are_idempotent(self, container):
        await container.scanner.start()
        assert container.scanner.running is True
        await container.scanner.start()  # no second task
        await container.scanner.stop()
        assert container.scanner.running is False
        await container.scanner.stop()
