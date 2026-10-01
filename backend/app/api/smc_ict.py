"""SMC / ICT endpoints (Phase 4).

* the current SMC/ICT objects, with their criteria, measurements, coordinates and
  drawing: BOS, CHOCH, MSS, equal highs/lows, liquidity pool ESTIMATES, sweeps,
  fair value gaps and their mitigation state, order blocks, breakers, dealing
  range, premium/discount and displacement;
* the structural objects only (BOS / CHOCH / MSS);
* the stored history (one row per object + candle, updated through its lifecycle);
* the SMC confluence groups - descriptive lists, never a score, never a signal;
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
from app.schemas.events import DetectionStatus, DetectionsResponse, PatternDetection
from app.smc_ict.params import SmcIctParams

router = APIRouter(prefix="/api", tags=["smc-ict"])
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
        "Confluence SMC/ICT informative : les objets sont regroupes, jamais notes, jamais "
        "transformes en recommandation."
    )


class ParamsUpdate(BaseModel):
    """Partial override of the centralised parameters (validated by pydantic)."""

    overrides: dict = Field(
        default_factory=dict,
        description='Nested groups, e.g. {"bos": {"min_break_pips": 2.0}, "sweep": {"max_scan_bars": 8}}',
    )


@router.get("/smc-ict", response_model=DetectionsResponse, summary="SMC/ICT objects")
async def smc_ict_detections(
    symbol: str | None = Query(default=None, description="Filter by pair, e.g. EURUSD"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe, e.g. M15"),
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    return container.smc_ict.response(symbol=symbol, timeframe=timeframe)


@router.get(
    "/smc-ict/structure",
    response_model=DetectionsResponse,
    summary="Structural SMC objects only (BOS, CHOCH, MSS)",
)
async def smc_ict_structure(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
    response.detections = container.smc_ict.structure(symbol=symbol, timeframe=timeframe)
    response.counts = {}
    for detection in response.detections:
        response.counts[detection.pattern] = response.counts.get(detection.pattern, 0) + 1
    response.status = "SMC STRUCTURE" if response.detections else "NO SMC STRUCTURE"
    return response


@router.get(
    "/smc-ict/liquidity",
    response_model=DetectionsResponse,
    summary="Equal highs/lows, liquidity pool estimates and sweeps",
)
async def smc_ict_liquidity(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
    liquidity = {
        "EQUAL_HIGH",
        "EQUAL_LOW",
        "LIQUIDITY_POOL_ESTIMATE",
        "LIQUIDITY_SWEEP",
    }
    response.detections = [
        d for d in response.detections if d.pattern in liquidity
    ]
    response.counts = {}
    for detection in response.detections:
        response.counts[detection.pattern] = response.counts.get(detection.pattern, 0) + 1
    response.status = "SMC LIQUIDITY (ESTIMATES)" if response.detections else "NO LIQUIDITY LEVEL"
    response.message = (
        "Les niveaux de liquidite sont des ESTIMATIONS geometriques : le moteur n'observe "
        "aucun carnet d'ordres."
    )
    return response


@router.get(
    "/smc-ict/gaps",
    response_model=DetectionsResponse,
    summary="Fair value gaps and their mitigation state",
)
async def smc_ict_gaps(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
    response.detections = [
        d for d in response.detections if d.pattern in ("BULLISH_FVG", "BEARISH_FVG")
    ]
    response.counts = {}
    for detection in response.detections:
        response.counts[detection.status.value] = response.counts.get(detection.status.value, 0) + 1
    response.status = "SMC GAPS" if response.detections else "NO ACTIVE GAP"
    return response


@router.get(
    "/smc-ict/blocks",
    response_model=DetectionsResponse,
    summary="Order blocks and breakers (breakers are derived, never detected alone)",
)
async def smc_ict_blocks(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
    response.detections = [
        d
        for d in response.detections
        if d.pattern in ("BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK", "BREAKER_BLOCK")
    ]
    response.counts = {}
    for detection in response.detections:
        response.counts[detection.pattern] = response.counts.get(detection.pattern, 0) + 1
    response.status = "SMC BLOCKS" if response.detections else "NO BLOCK"
    return response


@router.get(
    "/smc-ict/ranges",
    response_model=DetectionsResponse,
    summary="Dealing range, premium/discount and displacement",
)
async def smc_ict_ranges(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> DetectionsResponse:
    response = container.smc_ict.response(symbol=symbol, timeframe=timeframe)
    response.detections = [
        d
        for d in response.detections
        if d.pattern in ("DEALING_RANGE", "PREMIUM", "DISCOUNT", "DISPLACEMENT")
    ]
    response.counts = {}
    for detection in response.detections:
        response.counts[detection.pattern] = response.counts.get(detection.pattern, 0) + 1
    response.status = "SMC RANGE CONTEXT" if response.detections else "NO RANGE"
    return response


@router.get("/smc-ict/history", response_model=HistoryResponse, summary="Stored SMC/ICT history")
async def smc_ict_history(
    limit: int = Query(default=100, ge=1, le=500),
    symbol: str | None = None,
    timeframe: str | None = None,
    pattern: str | None = None,
    status: str | None = Query(
        default=None, description="DETECTED | ACTIVE | CONFIRMED | MITIGATED | FILLED | INVALIDATED | EXPIRED"
    ),
    container: Container = Depends(get_container),
) -> HistoryResponse:
    stored = container.smc_ict.history(
        limit=limit, symbol=symbol, timeframe=timeframe, pattern=pattern, status=status
    )
    return HistoryResponse(count=len(stored), status_filter=status, detections=stored)


@router.get(
    "/smc-ict/confluence",
    response_model=ConfluenceResponse,
    summary="Descriptive SMC/ICT confluence groups (structure + liquidity + gaps + blocks)",
)
async def smc_ict_confluence(
    symbol: str | None = None,
    timeframe: str | None = None,
    container: Container = Depends(get_container),
) -> ConfluenceResponse:
    groups = container.smc_ict.confluence(symbol=symbol, timeframe=timeframe)
    return ConfluenceResponse(count=len(groups), groups=groups)


@router.get("/smc-ict/params", summary="Centralised SMC/ICT parameters")
async def smc_ict_params(container: Container = Depends(get_container)) -> dict:
    return {
        "params": container.smc_ict.params.snapshot(),
        "engines": container.smc_ict.engines(),
        "stats": container.smc_ict.stats(),
        "trading_signal": False,
    }


@router.patch(
    "/smc-ict/params",
    summary="Override SMC/ICT parameters at runtime (validated, not persisted)",
)
async def update_smc_ict_params(
    payload: ParamsUpdate, container: Container = Depends(get_container)
) -> dict:
    current = container.smc_ict.params
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
        if "trading_signal" in values:  # frozen on purpose (§29)
            raise HTTPException(
                status_code=400,
                detail="trading_signal is frozen: the SMC/ICT engine never emits a trading signal",
            )
        data[group_key].update(values)

    try:  # pydantic re-validates every constraint (bounds included)
        updated = SmcIctParams.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    container.smc_ict.engine.params = updated
    logger.info("SMC/ICT parameters overridden at runtime: %s", ", ".join(sorted(payload.overrides)))
    return {
        "status": "UPDATED",
        "note": "Override applies to this process only; set the values in .env to persist them.",
        "params": updated.snapshot(),
        "changed_groups": sorted(payload.overrides.keys()),
    }


@router.get(
    "/smc-ict/{detection_id}",
    response_model=PatternDetection,
    summary="One SMC/ICT object, with its full evidence",
)
async def smc_ict_detail(
    detection_id: str, container: Container = Depends(get_container)
) -> PatternDetection:
    detection = container.smc_ict.engine.registry.get(detection_id)
    if detection is not None:
        return detection
    stored = container.detections_repo.get(detection_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Detection {detection_id} not found")
    return PatternDetection.model_validate(
        {**stored, "coordinates": stored.get("coordinates") or [], "evidence_points": {}}
    )
