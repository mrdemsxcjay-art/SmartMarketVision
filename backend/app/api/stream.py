"""Real-time endpoints: WebSocket ``/api/stream`` and SSE ``/api/events``.

Both publish the same :class:`MarketEvent` envelope produced by the scanner from
real market data. Clients may filter on a symbol and/or a timeframe; the server
still sends ``SYSTEM_STATUS`` heartbeats so the UI can distinguish
LIVE / RECONNECTING / DISCONNECTED honestly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from fastapi.responses import StreamingResponse

from app.api.deps import get_container, get_container_ws
from app.config import settings
from app.container import Container
from app.logging_conf import get_logger
from app.schemas.events import EventType, MarketEvent

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["stream"])


def _matches(event: MarketEvent, symbol: str | None, timeframe: str | None) -> bool:
    if event.event_type in (EventType.SYSTEM_STATUS, EventType.STREAM_HELLO):
        return True
    if symbol and (event.symbol or "").upper() != symbol.upper():
        return False
    if timeframe and event.timeframe and event.timeframe.value != timeframe.upper():
        return False
    return True


def _detections_snapshot(container: Container, symbol: str | None, timeframe: str | None) -> MarketEvent | None:
    """Current chartist state, sent to ONE connection (not broadcast).

    A dashboard that (re)connects must not wait for the next detection to show
    what the engine already knows. Returns ``None`` when nothing is tracked, so
    the client never receives a fabricated "empty detection".
    """
    try:
        response = container.patterns.response(symbol=symbol, timeframe=timeframe)
    except Exception as exc:  # pragma: no cover - the stream must never break here
        logger.warning("Could not build the detection snapshot: %s", exc)
        return None
    if not response.detections:
        return None
    return MarketEvent(
        event_type=EventType.DETECTIONS_SNAPSHOT,
        symbol=symbol.upper() if symbol else None,
        metadata={
            "status": response.status,
            "detections": [item.model_dump(mode="json") for item in response.detections],
            "counts": response.counts,
            "engines": {name: state.value for name, state in response.engines.items()},
            "stats": response.stats,
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        source="CHART_PATTERN_ENGINE",
    )


def _smc_ict_snapshot(
    container: Container, symbol: str | None, timeframe: str | None
) -> MarketEvent | None:
    """Current SMC/ICT state, sent to ONE connection (not broadcast).

    Same mechanism as the chartist and price-action snapshots: a reloading or
    reconnecting dashboard immediately sees the SMC objects already known by the
    engine. ``None`` when nothing is tracked - an empty list is never fabricated.
    """
    try:
        response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
        confluence = container.smc_ict.confluence(symbol=symbol, timeframe=timeframe)
    except Exception as exc:  # pragma: no cover - the stream must never break here
        logger.warning("Could not build the SMC/ICT snapshot: %s", exc)
        return None
    if not response.detections:
        return None
    return MarketEvent(
        event_type=EventType.SMC_ICT_SNAPSHOT,
        symbol=symbol.upper() if symbol else None,
        metadata={
            "status": response.status,
            "detections": [item.model_dump(mode="json") for item in response.detections],
            "counts": response.counts,
            "confluence": confluence,
            "engines": {name: state.value for name, state in response.engines.items()},
            "stats": response.stats,
            "trading_signal": False,
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        source="SMC_ICT_ENGINE",
    )


def _confluence_snapshot(
    container: Container, symbol: str | None, timeframe: str | None
) -> MarketEvent | None:
    """Current confluence state, sent to ONE connection (not broadcast).

    Same mechanism as the other snapshots: a reloading or reconnecting dashboard
    immediately sees the confluences already known by the engine. ``None`` when
    nothing is tracked - an empty list is never fabricated into a confluence.
    """
    try:
        groups = container.confluence.tracked(symbol=symbol, timeframe=timeframe)
        overview = container.confluence.overview(symbol=symbol, timeframe=timeframe)
        snapshot = container.confluence.snapshot(symbol=symbol, timeframe=timeframe)
    except Exception as exc:  # pragma: no cover - the stream must never break here
        logger.warning("Could not build the confluence snapshot: %s", exc)
        return None
    if not groups:
        return None
    return MarketEvent(
        event_type=EventType.CONFLUENCE_SNAPSHOT,
        symbol=symbol.upper() if symbol else None,
        metadata={
            "confluences": [group.as_dict() for group in groups],
            "overview": overview,
            "counts": snapshot["by_state"],
            "by_direction": snapshot["by_direction"],
            "stats": container.confluence.stats(),
            "trading_signal": False,
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        source="CONFLUENCE_ENGINE",
    )


def _opportunity_snapshot(
    container: Container, symbol: str | None, timeframe: str | None
) -> MarketEvent | None:
    """Current opportunity state, sent to ONE connection (not broadcast).

    Same mechanism as the confluence snapshot: a reloading dashboard immediately
    sees the observations already tracked, including the refusals with their
    reason. ``None`` when nothing is tracked - an observation is never invented.
    """
    try:
        items = container.opportunities.tracked(symbol=symbol, timeframe=timeframe)
        overview = container.opportunities.overview(symbol=symbol, timeframe=timeframe)
        snapshot = container.opportunities.snapshot(symbol=symbol, timeframe=timeframe)
    except Exception as exc:  # pragma: no cover - the stream must never break here
        logger.warning("Could not build the opportunity snapshot: %s", exc)
        return None
    if not items:
        return None
    return MarketEvent(
        event_type=EventType.OPPORTUNITY_SNAPSHOT,
        symbol=symbol.upper() if symbol else None,
        metadata={
            "opportunities": [item.as_dict() for item in items],
            "overview": overview,
            "counts": snapshot["by_state"],
            "by_direction": snapshot["by_direction"],
            "stats": container.opportunities.stats(),
            "trading_signal": False,
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        source="OPPORTUNITY_ENGINE",
    )


def _price_action_snapshot(
    container: Container, symbol: str | None, timeframe: str | None
) -> MarketEvent | None:
    """Current price-action state, sent to ONE connection (not broadcast).

    Same mechanism as the chartist snapshot: a reloading or reconnecting dashboard
    immediately sees what the price-action engine already detected. ``None`` when
    nothing is tracked - an empty list is never fabricated into a detection.
    """
    try:
        response = container.price_action.response(symbol=symbol, timeframe=timeframe)
        structure = container.price_action.structure(symbol=symbol, timeframe=timeframe)
    except Exception as exc:  # pragma: no cover - the stream must never break here
        logger.warning("Could not build the price-action snapshot: %s", exc)
        return None
    if not response.detections and not structure:
        return None
    return MarketEvent(
        event_type=EventType.PRICE_ACTION_SNAPSHOT,
        symbol=symbol.upper() if symbol else None,
        metadata={
            "status": response.status,
            "detections": [item.model_dump(mode="json") for item in response.detections],
            "structure": [item.model_dump(mode="json") for item in structure],
            "counts": response.counts,
            "engines": {name: state.value for name, state in response.engines.items()},
            "stats": response.stats,
            "trading_signal": False,
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
        source="PRICE_ACTION_ENGINE",
    )


def _hello_event(subscriber_id: int, container: Container) -> MarketEvent:
    return MarketEvent(
        event_type=EventType.STREAM_HELLO,
        metadata={
            "subscriber_id": subscriber_id,
            "provider": container.market.provider_name,
            "watchlist_size": len(settings.symbol_list),
            "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
            "scanner": container.scanner.status(),
            "protocol": "MarketEvent v1",
        },
        source="STREAM",
    )


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    container: Container = Depends(get_container_ws),
) -> None:
    await websocket.accept()
    bus = container.bus  # single bus per application instance (testable)
    subscriber_id, queue = await bus.subscribe()
    heartbeat_task: asyncio.Task | None = None

    try:
        await websocket.send_text(_hello_event(subscriber_id, container).model_dump_json())
        snapshot = _detections_snapshot(container, symbol, timeframe)
        if snapshot is not None:
            await websocket.send_text(snapshot.model_dump_json())
        price_action_snapshot = _price_action_snapshot(container, symbol, timeframe)
        if price_action_snapshot is not None:
            await websocket.send_text(price_action_snapshot.model_dump_json())
        smc_ict_snapshot = _smc_ict_snapshot(container, symbol, timeframe)
        if smc_ict_snapshot is not None:
            await websocket.send_text(smc_ict_snapshot.model_dump_json())
        confluence_snapshot = _confluence_snapshot(container, symbol, timeframe)
        if confluence_snapshot is not None:
            await websocket.send_text(confluence_snapshot.model_dump_json())

        opportunity_snapshot = _opportunity_snapshot(container, symbol, timeframe)
        if opportunity_snapshot is not None:
            await websocket.send_text(opportunity_snapshot.model_dump_json())

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(max(5, settings.stream_heartbeat_seconds))
                if websocket.client_state is not WebSocketState.CONNECTED:
                    return
                try:
                    await websocket.send_text(
                        MarketEvent(
                            event_type=EventType.SYSTEM_STATUS,
                            metadata={
                                "heartbeat": True,
                                "subscribers": bus.subscriber_count,
                                "server_time_utc": datetime.now(tz=timezone.utc).isoformat(),
                            },
                            source="STREAM",
                        ).model_dump_json()
                    )
                except (WebSocketDisconnect, RuntimeError):
                    return  # client already gone: nothing to report

        heartbeat_task = asyncio.create_task(heartbeat())

        while True:
            event = await queue.get()
            if not _matches(event, symbol, timeframe):
                continue
            if websocket.client_state is not WebSocketState.CONNECTED:
                break
            try:
                await websocket.send_text(event.model_dump_json())
            except (WebSocketDisconnect, RuntimeError):
                break
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected (subscriber #%s)", subscriber_id)
    except Exception as exc:  # pragma: no cover - transport errors
        logger.warning("WebSocket stream error (subscriber #%s): %s", subscriber_id, exc)
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        await bus.unsubscribe(subscriber_id)


@router.get("/events", summary="Server-Sent Events stream (fallback for WebSocket)")
async def sse_stream(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> StreamingResponse:
    bus = container.bus
    subscriber_id, queue = await bus.subscribe()

    async def generator():
        try:
            hello = _hello_event(subscriber_id, container)
            yield f"event: hello\ndata: {hello.model_dump_json()}\n\n"
            snapshot = _detections_snapshot(container, symbol, timeframe)
            if snapshot is not None:
                yield f"event: {snapshot.event_type.value}\ndata: {snapshot.model_dump_json()}\n\n"
            price_action_snapshot = _price_action_snapshot(container, symbol, timeframe)
            if price_action_snapshot is not None:
                yield (
                    f"event: {price_action_snapshot.event_type.value}\n"
                    f"data: {price_action_snapshot.model_dump_json()}\n\n"
                )
            smc_ict_snapshot = _smc_ict_snapshot(container, symbol, timeframe)
            if smc_ict_snapshot is not None:
                yield (
                    f"event: {smc_ict_snapshot.event_type.value}\n"
                    f"data: {smc_ict_snapshot.model_dump_json()}\n\n"
                )
            confluence_snapshot = _confluence_snapshot(container, symbol, timeframe)
            if confluence_snapshot is not None:
                yield (
                    f"event: {confluence_snapshot.event_type.value}\n"
                    f"data: {confluence_snapshot.model_dump_json()}\n\n"
                )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=settings.stream_heartbeat_seconds)
                    if not _matches(event, symbol, timeframe):
                        continue
                    yield f"event: {event.event_type.value}\ndata: {event.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:  # client closed the connection
            raise
        finally:
            await bus.unsubscribe(subscriber_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/status", summary="Stream counters")
async def stream_status(container: Container = Depends(get_container)) -> dict:
    bus = container.bus
    return {
        "subscribers": bus.subscriber_count,
        "events_published": bus.published_total,
        "websocket_endpoint": "/api/stream",
        "sse_endpoint": "/api/events",
        "heartbeat_seconds": settings.stream_heartbeat_seconds,
        "history": [event.model_dump(mode="json") for event in bus.history(5)],
    }
