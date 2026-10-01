"""Telegram endpoints (Phase 8).

The status and the alert history, with **no secret in the payload**: the token is
never returned, not even masked beyond the six-character preview already produced
by the Phase 1 notifier, and the queued messages never contain it either (the
outbox stores the text and a file path, nothing else).

There is also a ``/test`` route, which goes through the very same outbox as a real
alert: it is queued, dispatched and traced. Nothing is sent when the mode is
``NOT_CONFIGURED``, and nothing leaves the machine in ``DRY_RUN``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger
from app.schemas.market import Timeframe

router = APIRouter(prefix="/api", tags=["telegram"])
logger = get_logger(__name__)


class TelegramHistoryResponse(BaseModel):
    count: int
    alerts: list[dict] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    trading_signal: bool = False
    note: str = (
        "Historique reel de la file d'alertes. Le jeton du bot n'apparait jamais "
        "dans ces enregistrements."
    )


class TelegramParamsUpdate(BaseModel):
    overrides: dict = Field(
        default_factory=dict,
        description='Nested groups, e.g. {"delivery": {"max_attempts": 3}}. Le mode vient de .env uniquement.',
    )


#: ``/api/telegram/status`` and ``/api/telegram/test`` are served by ``api/system.py``:
#: they are the interface the Phase 1 exposed, upgraded to the Phase 8 outbox rather
#: than duplicated, so a dashboard never has two answers for the same question.

@router.get("/telegram/history", response_model=TelegramHistoryResponse, summary="Alert history")
async def telegram_history(
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None, description="QUEUED | SENDING | SENT | FAILED | RETRYING | SKIPPED"),
    container: Container = Depends(get_container),
) -> TelegramHistoryResponse:
    alerts = container.telegram.history(limit=limit, status=status)
    counts = container.telegram.repository.count_by_status()
    return TelegramHistoryResponse(count=len(alerts), alerts=alerts, counts=counts)


@router.get("/telegram/params", summary="Centralised Telegram parameters")
async def telegram_params(container: Container = Depends(get_container)) -> dict:
    return {
        "params": container.telegram.params.snapshot(),
        "groups": list(container.telegram.params.GROUPS),
        "mode": container.telegram.mode,
        "note": "Le mode (DRY_RUN / REAL) et le jeton viennent de .env : ils ne sont pas modifiables par l'API.",
    }


@router.patch("/telegram/params", summary="Adjust the message/delivery parameters at runtime")
async def update_telegram_params(
    payload: TelegramParamsUpdate,
    container: Container = Depends(get_container),
) -> dict:
    applied = container.telegram.params.apply_overrides(payload.overrides)
    logger.info("Telegram parameters updated: %s", applied)
    return {"applied": applied, "params": container.telegram.params.snapshot()}



