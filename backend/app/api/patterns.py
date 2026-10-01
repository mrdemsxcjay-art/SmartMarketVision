"""Chartist detection endpoints.

* the active formations, with their evidence, coordinates and drawing;
* the stored history (one row per formation, updated through its lifecycle);
* the centralised parameters, readable and (optionally) adjustable at runtime.

These endpoints only read or configure the detection engine: there is no order,
broker or position surface anywhere in this application.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger
from app.patterns.params import PatternParams
from app.schemas.events import DetectionStatus, DetectionsResponse, PatternDetection

router = APIRouter(prefix="/api", tags=["patterns"])
logger = get_logger(__name__)


class HistoryResponse(BaseModel):
    count: int
    status_filter: str | None = None
    detections: list[dict] = Field(default_factory=list)


class ParamsUpdate(BaseModel):
    """Partial override of the centralised parameters (validated by pydantic)."""

    overrides: dict = Field(
        default_factory=dict,
        description=(
            "Nested groups, e.g. {\"globals\": {\"window_bars\": 400}, "
            "\"double_top_bottom\": {\"peak_tolerance_pips\": 3}}"
        ),
    )


@router.get("/detections", response_model=DetectionsResponse, summary="Detections of the chartist engine")
async def detections(
    symbol: str | None = Query(default=None, description="Filter by pair, e.g. EURUSD"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe, e.g. M15"),
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.patterns.response(symbol=symbol, timeframe=timeframe)
    # the engine map is the truth of the running process: each engine reports its
    # own state (SMC/ICT is enabled since Phase 4)
    engines = dict(response.engines)
    engines.update(container.price_action.engines())
    engines.update(container.smc_ict.engines())
    response.engines = engines
    return response


@router.get(
    "/detections/active",
    response_model=DetectionsResponse,
    summary="Formations still waiting for their breakout",
)
async def active_detections(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.patterns.response(symbol=symbol, timeframe=timeframe)
    response.detections = [d for d in response.detections if d.status is DetectionStatus.DETECTED]
    response.status = "ACTIVE DETECTIONS" if response.detections else "NO ACTIVE DETECTION"
    response.counts = {"DETECTED": len(response.detections)}
    return response


@router.get("/detections/history", response_model=HistoryResponse, summary="Stored detection history")
async def detection_history(
    limit: int = Query(default=100, ge=1, le=500),
    symbol: str | None = None,
    timeframe: str | None = None,
    pattern: str | None = None,
    status: str | None = Query(default=None, description="DETECTED | CONFIRMED | INVALIDATED | EXPIRED"),
    container: Container = Depends(get_container),
) -> HistoryResponse:
    stored = container.patterns.history(
        limit=limit, symbol=symbol, timeframe=timeframe, pattern=pattern, status=status
    )
    return HistoryResponse(count=len(stored), status_filter=status, detections=stored)


@router.get(
    "/detections/{detection_id}",
    response_model=PatternDetection,
    summary="One detection, with its full evidence",
)
async def detection_detail(
    detection_id: str, container: Container = Depends(get_container)
) -> PatternDetection:
    detection = container.patterns.engine.registry.get(detection_id)
    if detection is not None:
        return detection
    stored = container.detections_repo.get(detection_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Detection {detection_id} not found")
    return PatternDetection.model_validate(
        {
            **stored,
            "coordinates": stored.get("coordinates") or [],
            "evidence_points": {},
        }
    )


@router.get(
    "/patterns/params",
    summary="Centralised detection parameters (the only place thresholds live)",
)
async def pattern_params(container: Container = Depends(get_container)) -> dict:
    return {
        "params": container.patterns.params.snapshot(),
        "engines": container.patterns.engines(),
        "stats": container.patterns.stats(),
    }


@router.patch(
    "/patterns/params",
    summary="Override detection parameters at runtime (validated, not persisted)",
)
async def update_pattern_params(
    payload: ParamsUpdate, container: Container = Depends(get_container)
) -> dict:
    current = container.patterns.params
    data = current.model_dump()
    for group, values in payload.overrides.items():
        group_key = "global_" if group == "globals" else group
        if group_key not in data:
            raise HTTPException(status_code=400, detail=f"Unknown parameter group '{group}'")
        if not isinstance(values, dict):
            raise HTTPException(status_code=400, detail=f"Group '{group}' expects an object")
        unknown = set(values) - set(data[group_key])
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"Unknown parameter(s) in '{group}': {sorted(unknown)}"
            )
        data[group_key].update(values)

    try:  # pydantic re-validates every constraint (bounds included)
        updated = PatternParams.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    container.patterns.engine.params = updated
    logger.info(
        "Pattern parameters overridden at runtime: %s",
        ", ".join(sorted(payload.overrides)),
    )
    return {
        "status": "UPDATED",
        "note": "Override applies to this process only; set the values in .env to persist them.",
        "params": updated.snapshot(),
        "changed_groups": sorted(payload.overrides.keys()),
    }
