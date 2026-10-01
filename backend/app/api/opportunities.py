"""Opportunity endpoints (Phase 6).

* the observations currently tracked, each with the full list of criteria that
  were checked (passed or not), the refusal reason when there is one, the real
  prices they refer to and the confluence they come from;
* one observation by id (live or stored);
* the stored history;
* the market-overview block used by the dashboard header;
* the centralised parameters, readable and adjustable at runtime.

``BUY`` / ``SELL`` are ANALYTICAL directions. This API cannot place an order: the
application has no broker and no execution surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.container import Container
from app.logging_conf import get_logger

router = APIRouter(prefix="/api", tags=["opportunities"])
logger = get_logger(__name__)


class OpportunityListResponse(BaseModel):
    count: int
    symbol: str | None = None
    timeframe: str | None = None
    opportunities: list[dict] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    directions: dict[str, int] = Field(default_factory=dict)
    engines: dict[str, str] = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)
    trading_signal: bool = False
    order_execution: bool = False
    note: str = (
        "Directions analytiques observees (BUY / SELL) : aucun ordre n'est envoye, "
        "aucun broker n'est connecte, aucune position n'existe. WATCH et NO_TRADE sont "
        "des refus explicites, toujours motives."
    )


class OpportunityHistoryResponse(BaseModel):
    count: int
    opportunities: list[dict] = Field(default_factory=list)


class OpportunityParamsUpdate(BaseModel):
    overrides: dict = Field(
        default_factory=dict,
        description='Nested groups, e.g. {"conditions": {"min_score": 7.0}, "lifecycle": {"cooldown_seconds": 600}}',
    )


@router.get("/opportunities", response_model=OpportunityListResponse, summary="Current opportunities")
async def opportunities_list(
    symbol: str | None = Query(default=None, description="Filter by pair, e.g. EURUSD"),
    timeframe: str | None = Query(default=None, description="Filter by timeframe, e.g. M15"),
    direction: str | None = Query(default=None, description="BUY | SELL | WATCH | NO_TRADE"),
    state: str | None = Query(default=None, description="CREATED | ACTIVE | CONFIRMED | WEAKENED | INVALIDATED | EXPIRED"),
    container: Container = Depends(get_container),
) -> OpportunityListResponse:
    items = container.opportunities.tracked(symbol, timeframe)
    if direction:
        wanted = direction.upper()
        items = [item for item in items if item.direction == wanted]
    if state:
        wanted_state = state.upper()
        items = [item for item in items if item.state == wanted_state]
    directions: dict[str, int] = {}
    states: dict[str, int] = {}
    for item in items:
        directions[item.direction] = directions.get(item.direction, 0) + 1
        states[item.state] = states.get(item.state, 0) + 1
    return OpportunityListResponse(
        count=len(items),
        symbol=symbol,
        timeframe=timeframe,
        opportunities=[item.as_dict() for item in items],
        counts=states,
        directions=directions,
        engines={name: status.value for name, status in container.opportunities.engines().items()},
        stats=container.opportunities.stats(),
    )


@router.get("/opportunities/overview", summary="Market overview block (dashboard header)")
async def opportunities_overview(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> dict:
    return container.opportunities.overview(symbol, timeframe)


@router.get("/opportunities/history", response_model=OpportunityHistoryResponse, summary="Stored opportunity history")
async def opportunities_history(
    limit: int = Query(default=100, ge=1, le=500),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    state: str | None = Query(default=None),
    container: Container = Depends(get_container),
) -> OpportunityHistoryResponse:
    items = container.opportunities.history(
        limit=limit, symbol=symbol, timeframe=timeframe, direction=direction, state=state
    )
    return OpportunityHistoryResponse(count=len(items), opportunities=items)


@router.get("/opportunities/params", summary="Centralised opportunity parameters")
async def opportunities_params(container: Container = Depends(get_container)) -> dict:
    return {
        "params": container.opportunities.params().snapshot(),
        "groups": list(container.opportunities.params().GROUPS),
        "note": (
            "Le score d'opportunite compte les criteres REELLEMENT verifies (structure, "
            "liquidite, desequilibre, declencheur, displacement, niveau de confluence). "
            "Ce n'est pas une probabilite de reussite."
        ),
    }


@router.patch("/opportunities/params", summary="Adjust the opportunity parameters at runtime")
async def update_opportunities_params(
    payload: OpportunityParamsUpdate,
    container: Container = Depends(get_container),
) -> dict:
    applied = container.opportunities.update_params(payload.overrides)
    return {"applied": applied, "params": container.opportunities.params().snapshot()}


@router.get("/opportunities/{opportunity_id}", summary="One opportunity (live or stored)")
async def opportunity_detail(opportunity_id: str, container: Container = Depends(get_container)) -> dict:
    item = container.opportunities.get(opportunity_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    return item.as_dict() if hasattr(item, "as_dict") else item
