"""System / status endpoints.

Nothing here can execute an order: the application has no trading surface at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_container
from app.config import settings
from app.container import Container
from app.providers.registry import registered_providers
from app.schemas.events import DetectorStatus, EventType

router = APIRouter(prefix="/api", tags=["system"])


class StreamStatus(BaseModel):
    websocket_endpoint: str = "/api/stream"
    sse_endpoint: str = "/api/events"
    subscribers: int
    events_published: int


class DatabaseStatus(BaseModel):
    backend: str
    candles_stored: int
    events_stored: int
    detections_stored: int
    retention_days: int


class SafetyStatus(BaseModel):
    order_execution: bool = False
    broker_connection: bool = False
    position_management: bool = False
    note: str = (
        "SMART MARKET VISION is a scanner: it observes and alerts. "
        "It never sends an order to any broker and holds no position."
    )


class StatusResponse(BaseModel):
    status: str
    server_time_utc: datetime
    app_env: str
    provider: str
    provider_health: dict
    available_providers: list[str]
    watchlist_size: int
    watchlist: list[str]
    timeframes: list[str]
    scanner: dict
    market: dict
    patterns: dict
    stream: StreamStatus
    database: DatabaseStatus
    telegram: dict
    capture: dict
    detection_engines: dict[str, DetectorStatus]
    safety: SafetyStatus
    config: dict
    cache: dict


@router.get("/status", response_model=StatusResponse, summary="Full system status (dashboard data-status card)")
async def status(container: Container = Depends(get_container)) -> StatusResponse:
    from app.schemas.market import Timeframe

    provider_health = await container.market.provider.health()
    market_status = await container.market.get_market_status()
    cache_stats = __import__("app.services.cache", fromlist=["series_cache"]).series_cache.stats()

    return StatusResponse(
        status="ok",
        server_time_utc=datetime.now(tz=timezone.utc),
        app_env=settings.app_env.value,
        provider=container.market.provider_name,
        provider_health=provider_health.model_dump(mode="json"),
        available_providers=registered_providers(),
        watchlist_size=len(settings.symbol_list),
        watchlist=settings.symbol_list,
        timeframes=[tf.value for tf in Timeframe],
        scanner=container.scanner.status(),
        market=market_status.model_dump(mode="json"),
        patterns={
            **container.patterns.stats(),
            "engines": {k: v.value for k, v in container.patterns.engines().items()},
        },
        stream=StreamStatus(
            subscribers=container.bus.subscriber_count,
            events_published=container.bus.published_total,
        ),
        database=DatabaseStatus(
            backend="sqlite" if settings.is_sqlite else "postgresql",
            candles_stored=_safe_count(container.candles_repo.count),
            events_stored=_safe_count(container.events_repo.count),
            detections_stored=_safe_count(container.detections_repo.count),
            retention_days=settings.database_retention_days,
        ),
        telegram=container.notifier.describe(),
        capture=container.snapshots.describe(),
        detection_engines={
            "CHART_PATTERN_ENGINE": (
                DetectorStatus.ENABLED
                if container.patterns.engines()["CHART_PATTERN_ENGINE"] is DetectorStatus.ENABLED
                else DetectorStatus.DISABLED
            ),
            # Phase 3: the price-action engine really runs, so the status card
            # reports its own state.
            "PRICE_ACTION_ENGINE": (
                DetectorStatus.ENABLED
                if container.price_action.engines()["PRICE_ACTION_ENGINE"] is DetectorStatus.ENABLED
                else DetectorStatus.DISABLED
            ),
            # Phase 4: the SMC/ICT engine is implemented and reports its own state.
            "SMC_ICT_ENGINE": (
                DetectorStatus.ENABLED
                if container.smc_ict.engines()["SMC_ICT_ENGINE"] is DetectorStatus.ENABLED
                else DetectorStatus.DISABLED
            ),
        },
        safety=SafetyStatus(),
        config=settings.safe_snapshot(),
        cache=cache_stats,
    )


@router.get("/events/recent", summary="Recently emitted market events (real data only)")
async def recent_events(
    limit: int = 50,
    symbol: str | None = None,
    container: Container = Depends(get_container),
) -> dict:
    limit = max(1, min(limit, 200))
    stored = container.events_repo.recent(limit=limit, symbol=symbol)
    live = [
        event.model_dump(mode="json")
        for event in container.bus.history(limit)
        if event.event_type is not EventType.SYSTEM_STATUS
    ]
    return {
        "stored_count": container.events_repo.count(),
        "stored": stored,
        "in_memory": live,
    }


@router.get("/database/coverage", summary="Stored candle coverage per symbol/timeframe")
async def coverage(container: Container = Depends(get_container)) -> dict:
    rows = container.candles_repo.coverage()
    return {"backend": "sqlite" if settings.is_sqlite else "postgresql", "series": rows, "series_count": len(rows)}


@router.get("/telegram/status", summary="Telegram availability, queue and dispatcher (no secret leaked)")
async def telegram_status(container: Container = Depends(get_container)) -> dict:
    """Phase 8 status, on the URL the Phase 1 interface already used.

    It keeps every key the Phase 1 payload exposed (``status``, presence flags and
    masked previews) and adds what the outbox knows: the real mode, the queue
    counters and the dispatcher state. No token, not even masked beyond the
    six-character preview.
    """
    live = container.telegram.status()
    notifier = live.get("notifier", {})
    return {
        **notifier,          # Phase 1 keys, unchanged
        **live,              # Phase 8 keys
        "status": live["mode"] if live["mode"] == "NOT_CONFIGURED" else notifier.get("status"),
        "legacy_status_key": notifier.get("status"),
        "trading_signal": False,
    }


@router.post("/telegram/test", summary="Queue a test alert through the real outbox")
async def telegram_test(container: Container = Depends(get_container)) -> dict:
    """The test goes through the outbox, exactly like a real alert.

    With ``NOT_CONFIGURED`` nothing can leave: the alert is reported as not sent.
    In ``DRY_RUN`` it is queued and marked sent by the dispatcher without any
    network call. The response keeps the Phase 1 shape (``status``,
    ``message_id``) so the interface stays backward compatible.
    """
    result = container.telegram.enqueue_test_alert()
    if container.telegram.mode == "NOT_CONFIGURED":
        return {
            "status": "NOT_CONFIGURED",
            "detail": "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are not both set",
            "message_id": None,
            "mode": container.telegram.mode,
            "queued": result,
            "trading_signal": False,
        }
    return {
        "status": "QUEUED" if result else "ALREADY_QUEUED",
        "detail": "alerte de test mise en file, le dispatcher s'en occupe",
        "message_id": None,
        "mode": container.telegram.mode,
        "queued": result,
        "trading_signal": False,
    }


@router.get("/capture/status", summary="Visual capture capability (real renderer since Phase 7)")
async def capture_status(container: Container = Depends(get_container)) -> dict:
    """Phase 1 contract kept for compatibility; the real state comes from Phase 7."""
    legacy = container.snapshots.describe()
    live = container.capture.describe()
    return {
        **live,
        "implemented": live["enabled"],
        "legacy_contract": legacy,
        "note": (
            "Les captures sont rendues depuis les bougies et les detections reelles "
            "(Pillow). Aucune image de substitution n'est jamais produite."
        ),
    }


def _safe_count(callable_) -> int:
    try:
        return int(callable_())
    except Exception:
        return -1
