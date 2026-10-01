"""Phase 4 - SMC / ICT engine.

An isolated analysis module. It reads the OHLC candles, reuses the Phase 2 pivots
(``app.services.structure.find_swings``) and the Phase 1 candle metrics, and
produces **descriptive** structure, liquidity, gap and block candidates.

Nothing in here executes anything: there is no order, no position, no signal.
Every candidate carries the criteria and the measurements that produced it, so
the dashboard can answer "why" for each line it draws.
"""

from __future__ import annotations

from app.smc_ict.context import build_context, dominant_structure, find_smc_swings
from app.smc_ict.models import (
    ALL_PATTERNS,
    BLOCKS,
    GAPS,
    LIQUIDITY,
    RANGE,
    STRUCTURAL,
    ScanContext,
    SmcCandidate,
    SmcSwing,
)
from app.smc_ict.params import SmcIctParams, params

__all__ = [
    "ALL_PATTERNS",
    "BLOCKS",
    "GAPS",
    "LIQUIDITY",
    "RANGE",
    "STRUCTURAL",
    "ScanContext",
    "SmcCandidate",
    "SmcIctParams",
    "SmcSwing",
    "build_context",
    "dominant_structure",
    "find_smc_swings",
    "params",
]
