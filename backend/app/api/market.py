"""Market data endpoints.

Contract for unavailable data: HTTP 200 with ``data_state = DATA_UNAVAILABLE``
and a null price, plus HTTP 503 only when the caller explicitly asked for data
that does not exist (candles). A fake price is never returned.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_container
from app.config import settings
from app.container import Container
from app.instruments import get_symbol_info, normalize_symbol
from app.logging_conf import get_logger
from app.providers.errors import ProviderError
from app.schemas.market import (
    CandleSeries,
    DataState,
    MarketStatus,
    QuoteSnapshot,
    SymbolInfo,
    Timeframe,
    as_timeframe,
)
from app.schemas.structure import StructureAnalysis
from app.services.structure import analyse_structure, recent_labels

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["market"])


def _validate_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if get_symbol_info(code) is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "INVALID_SYMBOL",
                "message": f"'{symbol}' is not a known instrument",
                "hint": "GET /api/symbols lists every available instrument",
            },
        )
    return code


def _validate_timeframe(timeframe: str) -> Timeframe:
    try:
        return as_timeframe(timeframe)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "INVALID_TIMEFRAME",
                "message": f"'{timeframe}' is not supported",
                "allowed": [tf.value for tf in Timeframe],
            },
        ) from None


@router.get("/symbols", summary="Watched instruments")
async def symbols(container: Container = Depends(get_container)) -> dict:
    items = await container.market.get_symbols()
    return {
        "provider": container.market.provider_name,
        "count": len(items),
        "timeframes": [tf.value for tf in Timeframe],
        "default_timeframe": settings.scanner_default_timeframe,
        "symbols": items,
    }


@router.get("/market/{symbol}", response_model=QuoteSnapshot, summary="Live snapshot for one pair")
async def market_snapshot(
    symbol: str,
    timeframe: str = Query(default="M15", description="M5 | M15 | H1 | H4 | D1"),
    container: Container = Depends(get_container),
) -> QuoteSnapshot:
    code = _validate_symbol(symbol)
    tf = _validate_timeframe(timeframe)
    return await container.market.get_quote(code, tf)


@router.get("/candles/{symbol}/{timeframe}", summary="Real OHLCV candles")
async def candles(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=400, ge=10, le=settings.max_candles_per_request),
    container: Container = Depends(get_container),
) -> dict:
    code = _validate_symbol(symbol)
    tf = _validate_timeframe(timeframe)
    try:
        series: CandleSeries = await container.market.get_candles(code, tf, limit=limit)
    except ProviderError as exc:
        # No fabricated fallback: the caller is told the data does not exist.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DATA_UNAVAILABLE",
                "data_state": DataState.DATA_UNAVAILABLE.value,
                "symbol": code,
                "timeframe": tf.value,
                "provider": container.market.provider_name,
                "cause": exc.code,
                "message": exc.message,
            },
        ) from exc

    info = get_symbol_info(code)
    return {
        "symbol": series.symbol,
        "timeframe": series.timeframe.value,
        "provider": series.provider,
        "data_state": series.data_state.value,
        "stale": series.stale,
        "digits": info.digits if info else 5,
        "pip_size": info.pip_size if info else 0.0001,
        "count": len(series.candles),
        "fetched_at": series.fetched_at.isoformat(),
        "quality_warnings": series.quality_warnings,
        "candles": [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "closed": c.closed,
                "iso": c.opened_at.isoformat(),
            }
            for c in series.candles
        ],
    }


@router.get("/structure/{symbol}/{timeframe}", response_model_exclude_none=False, summary="Phase-1 structure")
async def structure(
    symbol: str,
    timeframe: str,
    limit: int = Query(default=300, ge=20, le=settings.max_candles_per_request),
    pivot_left: int = Query(default=2, ge=1, le=10),
    pivot_right: int = Query(default=2, ge=1, le=10),
    include_forming: bool = Query(default=False, description="Include the still-forming candle"),
    container: Container = Depends(get_container),
) -> dict:
    code = _validate_symbol(symbol)
    tf = _validate_timeframe(timeframe)
    try:
        series = await container.market.get_candles(code, tf, limit=limit)
    except ProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "DATA_UNAVAILABLE",
                "symbol": code,
                "timeframe": tf.value,
                "cause": exc.code,
                "message": exc.message,
            },
        ) from exc

    analysis: StructureAnalysis = analyse_structure(
        code, tf, series.candles, left=pivot_left, right=pivot_right, closed_only=not include_forming
    )
    return {
        "symbol": analysis.symbol,
        "timeframe": analysis.timeframe.value,
        "provider": series.provider,
        "data_state": series.data_state.value,
        "trend": analysis.trend.value,
        "labels": [label.value for label in analysis.labels],
        "recent_labels": recent_labels(analysis, 4),
        "bars_analyzed": analysis.bars_analyzed,
        "using_closed_candles_only": analysis.using_closed_candles_only,
        "pivot_left": analysis.pivot_left,
        "pivot_right": analysis.pivot_right,
        "swing_count": len(analysis.swings),
        "last_swing_high": _swing_payload(analysis.last_swing_high),
        "last_swing_low": _swing_payload(analysis.last_swing_low),
        "swings": [
            {
                "index": s.index,
                "time": s.time,
                "iso": datetime.fromtimestamp(s.time, tz=timezone.utc).isoformat(),
                "price": s.price,
                "kind": s.kind.value,
                "label": s.label.value,
                "confirmed_at_index": s.confirmed_at_index,
            }
            for s in analysis.swings[-40:]
        ],
        "notes": analysis.notes,
        "evaluated_at": analysis.evaluated_at.isoformat(),
        "smc_ict": {
            "implemented": False,
            "message": "BOS / CHoCH / Order Blocks / FVG / liquidity are NOT computed in Phase 1.",
        },
    }


def _swing_payload(swing) -> dict | None:
    if swing is None:
        return None
    return {
        "index": swing.index,
        "time": swing.time,
        "iso": datetime.fromtimestamp(swing.time, tz=timezone.utc).isoformat(),
        "price": swing.price,
        "kind": swing.kind.value,
        "label": swing.label.value,
    }


@router.get("/market-status", response_model=MarketStatus, summary="Trading session status (clock-based)")
async def market_status(container: Container = Depends(get_container)) -> MarketStatus:
    return await container.market.get_market_status()


@router.get("/instruments/{symbol}", response_model=SymbolInfo, summary="Instrument metadata")
async def instrument(symbol: str) -> SymbolInfo:
    info = get_symbol_info(_validate_symbol(symbol))
    assert info is not None  # validated above
    return info
