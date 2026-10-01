"""Health endpoint. Contains no secret and no price."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_container
from app.config import settings
from app.container import Container

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    app_env: str
    provider: str
    database: str
    scanner_running: bool
    telegram: str
    version: str
    server_time_utc: datetime


class HealthComponent(BaseModel):
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    components: dict[str, HealthComponent]
    server_time_utc: datetime


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(container: Container = Depends(get_container)) -> HealthResponse:
    """Basic liveness: the process answers and knows its configuration."""
    return HealthResponse(
        status="ok",
        app_env=settings.app_env.value,
        provider=container.market.provider_name,
        database="sqlite" if settings.is_sqlite else "postgresql",
        scanner_running=container.scanner.running,
        telegram=settings.telegram_status,
        version=settings.api_title,
        server_time_utc=datetime.now(tz=timezone.utc),
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe (DB + provider)")
async def ready(container: Container = Depends(get_container)) -> ReadinessResponse:
    components: dict[str, HealthComponent] = {}

    try:
        integrity = container.candles_repo.count()
        components["database"] = HealthComponent(ok=True, detail=f"{integrity} candles stored")
    except Exception as exc:
        components["database"] = HealthComponent(ok=False, detail=f"{type(exc).__name__}: {exc}")

    try:
        provider_health = await container.market.provider.health()
        detail = "reachable" if provider_health.reachable else (provider_health.last_error or "not reachable yet")
        components["provider"] = HealthComponent(ok=provider_health.reachable, detail=detail)
    except Exception as exc:
        components["provider"] = HealthComponent(ok=False, detail=f"{type(exc).__name__}: {exc}")

    components["scanner"] = HealthComponent(
        ok=container.scanner.running, detail=f"{container.scanner.ticks} tick(s) executed"
    )

    overall = "ok" if all(component.ok for component in components.values()) else "degraded"
    return ReadinessResponse(
        status=overall, components=components, server_time_utc=datetime.now(tz=timezone.utc)
    )
