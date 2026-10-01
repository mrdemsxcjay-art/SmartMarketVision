"""Confluence Engine data models (Phase 5).

Two families of objects:

* :class:`ConfluenceEvent` - the **normalised** view of one detection produced by
  one of the three engines. It keeps the source detection id, so the identity of
  an event survives the whole chain (detection -> confluence -> opportunity ->
  capture -> alert). Timeframes are never mixed without being written on the
  event itself.
* :class:`ConfluenceGroup` - a set of events that agree in time, in price and in
  direction, with an explicit score breakdown, an explicit state and the explicit
  reasons why they agree (:attr:`ConfluenceGroup.why`) and what opposes them
  (:attr:`ConfluenceGroup.against`).

No probability, no forecast, no order: a confluence describes what several
independent readers of the same market are saying at the same moment.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.events import DetectionDirection


class ConfluenceDimension(str, Enum):
    """One independent kind of reading. One dimension earns its weight once."""

    STRUCTURE = "STRUCTURE"
    LIQUIDITY = "LIQUIDITY"
    IMBALANCE = "IMBALANCE"
    DISPLACEMENT = "DISPLACEMENT"
    PRICE_ACTION = "PRICE_ACTION"
    CHARTISTE = "CHARTISTE"
    PREMIUM_DISCOUNT = "PREMIUM_DISCOUNT"
    MULTI_TIMEFRAME = "MULTI_TIMEFRAME"


class ConfluenceState(str, Enum):
    """Contextual state. Descriptive only - never an instruction."""

    NO_CONFLUENCE = "NO_CONFLUENCE"
    WATCH = "WATCH"
    CONFLUENCE = "CONFLUENCE"
    STRONG_CONFLUENCE = "STRONG_CONFLUENCE"
    CONTRADICTED = "CONTRADICTED"
    EXPIRED = "EXPIRED"


class ConfluenceEvent(BaseModel):
    """Normalised detection (5.1): the common format shared by the three engines.

    ``id`` is the **source detection id**: the same object keeps the same identity
    from the detector to the alert. Nothing is re-keyed and nothing is invented.
    """

    id: str
    symbol: str
    timeframe: str
    source: str  # CHARTISTE | PRICE_ACTION | SMC_ICT
    type: str  # pattern name, exactly as the source engine published it
    direction: str  # BULLISH | BEARISH | NEUTRAL
    dimension: str  # ConfluenceDimension value, from the documented map
    timestamp: int  # epoch seconds of the bar the detection is tied to
    price: float | None = None
    status: str = "ACTIVE"
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")


class ScoreComponent(BaseModel):
    """One traceable line of the score: who earned the point and why."""

    dimension: str
    label: str
    points: float
    reason: str
    events: list[str] = Field(default_factory=list)  # source detection ids
    timeframes: list[str] = Field(default_factory=list)


class ConfluenceGroup(BaseModel):
    """A scored, timestamped agreement between several readings (5.4 - 5.7)."""

    id: str
    dedup_key: str
    signature: str
    symbol: str
    timeframe: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    state: str  # ConfluenceState value
    score: float
    max_score: float
    dimensions: list[str] = Field(default_factory=list)
    components: list[ScoreComponent] = Field(default_factory=list)
    contradictions: list[ScoreComponent] = Field(default_factory=list)
    events: list[ConfluenceEvent] = Field(default_factory=list)
    #: every event observed inside the window (aligned, opposing OR context), each
    #: one keeping its own direction, timeframe and source detection id. Which of
    #: them earned or cost points is said by ``components`` / ``contradictions``.
    why: list[str] = Field(default_factory=list)
    against: list[str] = Field(default_factory=list)
    multi_timeframe: list[dict] = Field(default_factory=list)
    reference_price: float | None = None
    anchor_time: int = 0
    window_start: int = 0
    window_end: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    previous_state: str | None = None
    state_since: datetime | None = None
    generation: int = 1
    note: str = ""

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")

    def compact(self) -> dict:
        """Small payload for the WebSocket snapshot and the dashboard header."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "state": self.state,
            "score": self.score,
            "max_score": self.max_score,
            "dimensions": self.dimensions,
            "events": len(self.events),
            "anchor_time": self.anchor_time,
            "reference_price": self.reference_price,
        }


class SeriesConfluence(BaseModel):
    """Result of one confluence run on one series."""

    symbol: str
    timeframe: str
    bars_analyzed: int = 0
    events_considered: int = 0
    events_aligned: int = 0
    groups: list[ConfluenceGroup] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


def opposite(direction: str) -> str:
    """The mirror direction, or NEUTRAL when there is nothing to mirror."""
    if direction == DetectionDirection.BULLISH.value:
        return DetectionDirection.BEARISH.value
    if direction == DetectionDirection.BEARISH.value:
        return DetectionDirection.BULLISH.value
    return DetectionDirection.NEUTRAL.value
