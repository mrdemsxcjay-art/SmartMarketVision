"""SMART MARKET VISION - FastAPI application.

A market SCANNER: it reads real market data, derives structure and streams it
to the dashboard. It has no order, broker or position capability of any kind.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import confluence as confluence_router
from app.api import captures as captures_router
from app.api import opportunities as opportunities_router
from app.api import telegram as telegram_router
from app.api import health as health_router
from app.api import market as market_router
from app.api import patterns as patterns_router
from app.api import price_action as price_action_router
from app.api import smc_ict as smc_ict_router
from app.api import stream as stream_router
from app.api import system as system_router
from app.config import settings
from app.container import Container, container
from app.db.base import init_db
from app.logging_conf import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SMART MARKET VISION (env=%s)", settings.app_env.value)
    logger.info("Configuration: %s", settings.safe_snapshot())

    init_db()

    app.state.container: Container = getattr(app.state, "container", None) or container
    service = app.state.container

    #: the capture worker renders off the event loop; the market stream never waits
    service.capture.start_worker()
    if service.opportunities.outbox is not None:
        await service.opportunities.outbox.start()  # Telegram outbox (Phase 8)

    if settings.scanner_enabled:
        await service.scanner.start()
        # Warm the cache so the first dashboard load is already real data.
        import asyncio

        asyncio.create_task(
            service.market.warm(
                settings.symbol_list, settings.scanner_default_timeframe, 300
            )
        )
    else:
        logger.warning("Scanner disabled by configuration (SCANNER_ENABLED=false)")

    try:
        yield
    finally:
        logger.info("Shutting down SMART MARKET VISION")
        if settings.scanner_enabled:
            await service.scanner.stop()
        if service.opportunities.outbox is not None:
            await service.opportunities.outbox.stop()
        await service.capture.stop_worker()
        await service.notifier.aclose()
        await service.market.provider.aclose()


app = FastAPI(
    title=settings.api_title,
    version="1.0.0-phase8",
    description=(
        "Market scanner on real Forex data: structure primitives, a chartist pattern "
        "engine (Phase 2), a price-action engine (Phase 3), an SMC/ICT engine (Phase 4) "
        "and a confluence engine (Phase 5) over real, unmodified detections. "
        "No order execution of any kind."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health_router.router, prefix="/api")
app.include_router(market_router.router)
app.include_router(system_router.router)
app.include_router(stream_router.router)
app.include_router(patterns_router.router)
app.include_router(price_action_router.router)
app.include_router(smc_ict_router.router)
app.include_router(confluence_router.router)
app.include_router(opportunities_router.router)
app.include_router(captures_router.router)
app.include_router(telegram_router.router)


@app.get("/api", include_in_schema=False)
async def api_root() -> dict:
    return {
        "name": "SMART MARKET VISION",
        "phase": "3 - price action engine",
        "docs": "/docs",
        "health": "/api/health",
        "symbols": "/api/symbols",
        "status": "/api/status",
        "websocket": "/api/stream",
        "sse": "/api/events",
        "detections": "/api/detections",
        "active_detections": "/api/detections/active",
        "detection_history": "/api/detections/history",
        "pattern_params": "/api/patterns/params",
        "price_action": "/api/price-action",
        "price_action_active": "/api/price-action/active",
        "price_action_structure": "/api/price-action/structure",
        "price_action_history": "/api/price-action/history",
        "price_action_confluence": "/api/price-action/confluence",
        "price_action_params": "/api/price-action/params",
        "smc_ict": "/api/smc-ict",
        "confluence": "/api/confluence",
        "confluence_overview": "/api/confluence/overview",
        "confluence_history": "/api/confluence/history",
        "confluence_params": "/api/confluence/params",
        "opportunities": "/api/opportunities",
        "opportunities_overview": "/api/opportunities/overview",
        "opportunities_history": "/api/opportunities/history",
        "opportunities_params": "/api/opportunities/params",
        "captures": "/api/captures",
        "capture_detail": "/api/captures/{id}",
        "capture_file": "/api/captures/{id}/file",
        "telegram_status": "/api/telegram/status",
        "telegram_history": "/api/telegram/history",
        "telegram_params": "/api/telegram/params",
        "order_execution": False,
    }


# ---------------------------------------------------------------- frontend
# The built React dashboard is served by the same process: one command to run.
_FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"
# `dashboard_build` is the kept build directory; `dist` is still accepted so an
# older checkout (or a plain `--outDir dist` build) keeps working.
FRONTEND_DIST = next(
    (
        candidate
        for candidate in (_FRONTEND_ROOT / "dashboard_build", _FRONTEND_ROOT / "dist")
        if candidate.is_dir()
    ),
    _FRONTEND_ROOT / "dashboard_build",
)
if FRONTEND_DIST.is_dir():
    # Mounted LAST so /api/* keeps priority. Served at "/" (and at /app for the
    # documented URL) in one single process, one single port.
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="dashboard")
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="dashboard-root")
    logger.info(
        "Serving built dashboard from %s - open http://localhost:%s/ (or /app/)",
        FRONTEND_DIST,
        settings.api_port,
    )
else:
    logger.info("No frontend build found at %s - run 'npm run build' in frontend/", FRONTEND_DIST)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request, exc: StarletteHTTPException):
    """Uniform JSON error envelope."""
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "HTTP_ERROR", "message": str(detail)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc: Exception):  # pragma: no cover
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_ERROR", "message": "unexpected server error - see server logs"},
    )
