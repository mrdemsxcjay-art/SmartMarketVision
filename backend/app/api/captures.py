"""Capture endpoints (Phase 7).

* the gallery of real captures with their metadata (id, opportunity, pair,
  timeframe, timestamp, path, hash, size, resolution, overlays);
* one capture by id, and the PNG itself;
* the renderer state (queue, worker, counters) and the centralised parameters.

Every file served here was rendered from a real candle series and real
detections. When there is no data, the API answers ``CAPTURE_FAILED_NO_DATA`` and
no file is created: there is no placeholder image anywhere in this project.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger

router = APIRouter(prefix="/api", tags=["captures"])
logger = get_logger(__name__)


class CaptureListResponse(BaseModel):
    count: int
    captures: list[dict] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    trading_signal: bool = False
    note: str = (
        "Captures rendues depuis les bougies et les detections reelles. Aucune image "
        "de substitution, aucune donnee inventee."
    )


class CaptureParamsUpdate(BaseModel):
    overrides: dict = Field(
        default_factory=dict,
        description='Nested groups, e.g. {"overlays": {"max_labels": 12}, "layout": {"candle_count": 90}}',
    )


@router.get("/captures", response_model=CaptureListResponse, summary="Real chart captures")
async def captures_list(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None),
    opportunity_id: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> CaptureListResponse:
    items = container.capture.history(limit=limit, symbol=symbol, opportunity_id=opportunity_id)
    return CaptureListResponse(
        count=len(items), captures=items, stats=container.capture.stats()
    )


@router.get("/captures/stats", summary="Capture engine state")
async def captures_stats(container: Container = Depends(get_container)) -> dict:
    return container.capture.describe()


@router.get("/captures/params", summary="Centralised capture parameters")
async def captures_params(container: Container = Depends(get_container)) -> dict:
    return {"params": container.capture.params.snapshot(), "groups": list(container.capture.params.GROUPS)}


@router.patch("/captures/params", summary="Adjust the capture parameters at runtime")
async def update_captures_params(
    payload: CaptureParamsUpdate,
    container: Container = Depends(get_container),
) -> dict:
    applied = container.capture.params.apply_overrides(payload.overrides)
    logger.info("Capture parameters updated: %s", applied)
    return {"applied": applied, "params": container.capture.params.snapshot()}


@router.get("/captures/{capture_id}", summary="One capture and its metadata")
async def capture_detail(capture_id: str, container: Container = Depends(get_container)) -> dict:
    row = container.capture.get(capture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Capture {capture_id} not found")
    return row


@router.get("/captures/{capture_id}/file", summary="The PNG itself")
async def capture_file(
    capture_id: str,
    tier: str = Query(default="phone", description="phone | telegram"),
    container: Container = Depends(get_container),
) -> FileResponse:
    row = container.capture.get(capture_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Capture {capture_id} not found")
    path = row.get("telegram_path") if tier == "telegram" else row.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=410, detail="Le fichier de cette capture n'existe plus sur le disque")
    return FileResponse(path, media_type="image/png", filename=Path(path).name)
