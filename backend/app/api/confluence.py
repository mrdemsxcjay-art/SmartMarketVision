"""Confluence endpoints (Phase 5).

* the confluences currently tracked, with their score **breakdown**, their state,
  the source events (each one with its own id and timeframe) and the explicit
  ``why`` / ``against`` lists;
* one confluence by id (live state or stored row);
* the stored history;
* the market-overview block used by the dashboard header;
* the centralised parameters, readable and (optionally) adjustable at runtime.

Everything here is descriptive: no probability, no forecast, no recommendation and
no order surface anywhere in this application.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger

router = APIRouter(prefix="/api", tags=["confluence"])
logger = get_logger(__name__)


class ConfluenceListResponse(BaseModel):
    count: int
    symbol: str | None = None
    timeframe: str | None = None
    confluences: list[dict] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    engines: dict[str, str] = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)
    trading_signal: bool = False
    note: str = (
        "Confluence descriptive : plusieurs lectures independantes concordent. "
        "Aucune probabilite de reussite, aucun ordre, aucune execution."
    )


class ConfluenceHistoryResponse(BaseModel):
    count: int
    confluences: list[dict] = Field(default_factory=list)


class ConfluenceParamsUpdate(BaseModel):
    overrides: dict = Field(
        default_factory=dict,
        description='Nested groups, e.g. {"globals": {"window_bars": 8}, "states": {"confluence_score": 5}}',
    )


@router.get("/confluence", response_model=ConfluenceListResponse, summary="Current confluences")
async def confluence_list(
    symbol: str | None = Query(default=None, description="Filter by pair, e.g. EURUSD"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe, e.g. M15"),
    state: str | None = Query(default=None, description="Filter by state (WATCH, CONFLUENCE, ...)"),
    container: Container = Depends(get_container),
) -> ConfluenceListResponse:
    groups = container.confluence.tracked(symbol, timeframe)
    if state:
        wanted = state.upper()
        groups = [group for group in groups if group.state == wanted]
    counts: dict[str, int] = {}
    for group in groups:
        counts[group.state] = counts.get(group.state, 0) + 1
    return ConfluenceListResponse(
        count=len(groups),
        symbol=symbol,
        timeframe=timeframe,
        confluences=[group.as_dict() for group in groups],
        counts=counts,
        engines={name: status.value for name, status in container.confluence.engines().items()},
        stats=container.confluence.stats(),
    )


@router.get("/confluence/overview", summary="Market overview block (dashboard header)")
async def confluence_overview(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> dict:
    return container.confluence.overview(symbol, timeframe)


@router.get("/confluence/history", response_model=ConfluenceHistoryResponse, summary="Stored confluence history")
async def confluence_history(
    limit: int = Query(default=100, ge=1, le=500),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    state: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> ConfluenceHistoryResponse:
    items = container.confluence.history(
        limit=limit, symbol=symbol, timeframe=timeframe, state=state, direction=direction
    )
    return ConfluenceHistoryResponse(count=len(items), confluences=items)


@router.get("/confluence/params", summary="Centralised confluence parameters")
async def confluence_params(container: Container = Depends(get_container)) -> dict:
    params = container.confluence.params()
    return {
        "params": params.snapshot(),
        "groups": list(params.GROUPS),
        "note": (
            "Le score additionne UN point par dimension : une dimension gagne son poids une "
            "seule fois, quel que soit le nombre d'evenements. Les contradictions retirent des "
            "points et sont listees separement."
        ),
    }


@router.patch("/confluence/params", summary="Adjust the confluence parameters at runtime")
async def update_confluence_params(
    payload: ConfluenceParamsUpdate,
    container: Container = Depends(get_container),
) -> dict:
    applied = container.confluence.update_params(payload.overrides)
    return {"applied": applied, "params": container.confluence.params().snapshot()}


@router.get("/confluence/{confluence_id}", summary="One confluence (live or stored)")
async def confluence_detail(confluence_id: str, container: Container = Depends(get_container)) -> dict:
    group = container.confluence.get(confluence_id)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Confluence {confluence_id} not found")
    if hasattr(group, "as_dict"):
        return group.as_dict()
    return group
