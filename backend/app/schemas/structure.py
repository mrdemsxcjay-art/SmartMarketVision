"""Generic market-structure primitives.

Phase 1 deliberately stops at the *primitives*: swing points and their
HH / HL / LH / LL labels plus a structural trend. No SMC/ICT claim is made
here - those detectors belong to later phases.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.market import Timeframe


class SwingKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class SwingLabel(str, Enum):
    HIGHER_HIGH = "HH"
    HIGHER_LOW = "HL"
    LOWER_HIGH = "LH"
    LOWER_LOW = "LL"
    FIRST_HIGH = "H"
    FIRST_LOW = "L"
    UNKNOWN = "?"


class StructuralTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    UNDEFINED = "UNDEFINED"


class SwingPoint(BaseModel):
    """A confirmed pivot high/low."""

    index: int = Field(description="Index of the pivot bar inside the analysed window")
    time: int = Field(description="Pivot bar open time, UTC epoch seconds")
    price: float
    kind: SwingKind
    label: SwingLabel = SwingLabel.UNKNOWN
    confirmed_at_index: int = Field(description="Bar index at which the pivot became confirmable")

    @property
    def is_high(self) -> bool:
        return self.kind is SwingKind.HIGH


class StructureAnalysis(BaseModel):
    symbol: str
    timeframe: Timeframe
    trend: StructuralTrend = StructuralTrend.UNDEFINED
    labels: list[SwingLabel] = Field(default_factory=list)
    swings: list[SwingPoint] = Field(default_factory=list)
    last_swing_high: SwingPoint | None = None
    last_swing_low: SwingPoint | None = None
    bars_analyzed: int = 0
    pivot_left: int = 2
    pivot_right: int = 2
    evaluated_at: datetime
    using_closed_candles_only: bool = True
    notes: list[str] = Field(default_factory=list)


class StructureQuery(BaseModel):
    symbol: str
    timeframe: Timeframe
