"""Price-action endpoints (Phase 3).

* the active price-action detections, with their evidence, measured values,
  coordinates and drawing;
* the structural states (impulsion, consolidation) of the watched series;
* the stored history (one row per pattern + candle, updated through its lifecycle);
* the confluence groups (informative only: no score, no signal);
* the centralised parameters, readable and (optionally) adjustable at runtime.

These endpoints only read or configure an observation engine: there is no order,
broker or position surface anywhere in this application.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger
from app.price_action.params import PriceActionParams
from app.schemas.events import DetectionStatus, DetectionsResponse, PatternDetection

router = APIRouter(prefix="/api", tags=["price-action"])
logger = get_logger(__name__)


class HistoryResponse(BaseModel):
    count: int
    status_filter: str | None = None
    detections: list[dict] = Field(default_factory=list)


class ConfluenceResponse(BaseModel):
    count: int
    groups: list[dict] = Field(default_factory=list)
    trading_signal: bool = False
    note: str = (
        "Confluence informative : les trois moteurs sont regroupes, jamais notes, jamais "
        "transformes en recommandation."
    )


class ParamsUpdate(BaseModel):
    """Partial override of the centralised parameters (validated by pydantic)."""

    overrides: dict = Field(
        default_factory=dict,
        description=(
            "Nested groups, e.g. {\"globals\": {\"scan_bars\": 20}, "
            "\"engulfing\": {\"min_coverage\": 1.0}}"
        ),
    )


@router.get("/price-action", response_model=DetectionsResponse, summary="Price-action detections")
async def price_action_detections(
    symbol: str | None = Query(default=None, description="Filter by pair, e.g. EURUSD"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe, e.g. M15"),
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    return container.price_action.response(symbol=symbol, timeframe=timeframe)


@router.get(
    "/price-action/active",
    response_model=DetectionsResponse,
    summary="Price-action detections still waiting for a confirmation close",
)
async def active_price_action(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.price_action.response(symbol=symbol, timeframe=timeframe)
    response.detections = [d for d in response.detections if d.status is DetectionStatus.DETECTED]
    response.status = "ACTIVE PRICE ACTION" if response.detections else "NO ACTIVE PRICE ACTION"
    response.counts = {"DETECTED": len(response.detections)}
    return response


@router.get(
    "/price-action/structure",
    response_model=DetectionsResponse,
    summary="Measured market states (impulsion, consolidation)",
)
async def structure_states(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.price_action.response(symbol=symbol, timeframe=timeframe)
    response.detections = container.price_action.structure(symbol=symbol, timeframe=timeframe)
    response.counts = {d.pattern: 0 for d in response.detections}
    for detection in response.detections:
        response.counts[detection.pattern] = response.counts.get(detection.pattern, 0) + 1
    response.status = "STRUCTURE STATES" if response.detections else "NO STATE MEASURED"
    return response


@router.get("/price-action/history", response_model=HistoryResponse, summary="Stored price-action history")
async def price_action_history(
    limit: int = Query(default=100, ge=1, le=500),
    symbol: str | None = None,
    timeframe: str | None = None,
    pattern: str | None = None,
    status: str | None = Query(default=None, description="DETECTED | CONFIRMED | INVALIDATED | EXPIRED"),
    container: Container = Depends(get_container),
) -> HistoryResponse:
    stored = container.price_action.history(
        limit=limit, symbol=symbol, timeframe=timeframe, pattern=pattern, status=status
    )
    return HistoryResponse(count=len(stored), status_filter=status, detections=stored)


@router.get(
    "/price-action/confluence",
    response_model=ConfluenceResponse,
    summary="Informative grouping of chartist / price action / structure",
)
async def confluence(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> ConfluenceResponse:
    chartist = container.patterns.tracked(symbol=symbol, timeframe=timeframe)
    groups = container.price_action.confluence(symbol=symbol, timeframe=timeframe, chartist=chartist)
    return ConfluenceResponse(count=len(groups), groups=groups)


@router.get("/price-action/params", summary="Centralised price-action parameters")
async def price_action_params(container: Container = Depends(get_container)) -> dict:
    return {
        "params": container.price_action.params.snapshot(),
        "engines": container.price_action.engines(),
        "stats": container.price_action.stats(),
    }


@router.patch(
    "/price-action/params",
    summary="Override price-action parameters at runtime (validated, not persisted)",
)
async def update_price_action_params(
    payload: ParamsUpdate, container: Container = Depends(get_container)
) -> dict:
    current = container.price_action.params
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
        updated = PriceActionParams.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    container.price_action.engine.params = updated
    logger.info(
        "Price-action parameters overridden at runtime: %s", ", ".join(sorted(payload.overrides))
    )
    return {
        "status": "UPDATED",
        "note": "Override applies to this process only; set the values in .env to persist them.",
        "params": updated.snapshot(),
        "changed_groups": sorted(payload.overrides.keys()),
    }


@router.get(
    "/price-action/{detection_id}",
    response_model=PatternDetection,
    summary="One price-action detection, with its full evidence",
)
async def price_action_detail(
    detection_id: str, container: Container = Depends(get_container)
) -> PatternDetection:
    detection = container.price_action.engine.registry.get(detection_id)
    if detection is not None:
        return detection
    stored = container.detections_repo.get(detection_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Detection {detection_id} not found")
    return PatternDetection.model_validate(
        {**stored, "coordinates": stored.get("coordinates") or [], "evidence_points": {}}
    )
