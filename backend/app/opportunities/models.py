"""Opportunity Engine data models (Phase 6).

``BUY`` / ``SELL`` are **analytical directions observed**, never orders: the
application has no broker, no execution surface, no position. ``WATCH`` is the
honest "something is happening but it is not actionable yet" and ``NO_TRADE`` is
the explicit refusal, always carrying its reason.

An opportunity always carries:

* the id of the confluence it comes from (identity preserved end to end);
* the ids of the source detections (through the confluence components);
* every criterion that was checked, passed or not, with its detail;
* an explicit state and an expiration;
* a stable anti-spam key.

No probability of success, no forecast, no performance: those words are absent
from the vocabulary on purpose.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OpportunityDirection(str, Enum):
    """Analytical direction. Descriptive vocabulary - never an instruction."""

    BUY = "BUY"
    SELL = "SELL"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"


class OpportunityState(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    WEAKENED = "WEAKENED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class NoTradeReason(str, Enum):
    """Why no direction is named. Never empty when the direction is NO_TRADE."""

    INSUFFICIENT_CONFLUENCE = "CONFLUENCE_INSUFFISANTE"
    CONTRADICTORY = "DIRECTIONS_CONTRADICTOIRES"
    MISSING_DIMENSIONS = "STRUCTURE_NON_CONFIRMEE"
    STALE_DATA = "DONNEES_TROP_ANCIENNES"
    LOW_VOLATILITY = "VOLATILITE_INSUFFISANTE"
    EXPIRED = "EVENEMENT_EXPIRE"
    DISABLED = "MOTEUR_DESACTIVE"


class OpportunityCondition(BaseModel):
    """One criterion of 6.2, with its real measurement and its points."""

    label: str
    passed: bool
    detail: str
    points: float = 0.0
    dimension: str | None = None
    #: a gate blocks the direction without adding points to the score
    gate: bool = False


class WatchedLevel(BaseModel):
    """A real price the observation refers to (the level it came from)."""

    label: str
    price: float
    kind: str = "REFERENCE"
    note: str = ""


class Opportunity(BaseModel):
    id: str
    dedup_key: str
    symbol: str
    timeframe: str
    direction: str
    state: str
    score: float
    max_score: float
    confluence_id: str | None = None
    confluence_state: str | None = None
    reference_price: float | None = None
    conditions: list[OpportunityCondition] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    no_trade_reason: str | None = None
    #: why no direction is named yet (also filled for a WATCH, which is transparent)
    blocked_by: str | None = None
    watch_levels: list[WatchedLevel] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: real bar time of the reading (never a wall clock invented value)
    observed_bar_time: int | None = None
    #: bar time of the candle that confirmed an observation, when there is one
    confirmation_bar_time: int | None = None
    expires_at: datetime | None = None
    generation: int = 1
    #: stable key of the observation (anti-spam, 6.6)
    alert_key: str | None = None
    previous_state: str | None = None
    note: str = ""

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")

    def compact(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "state": self.state,
            "score": self.score,
            "max_score": self.max_score,
            "confluence_id": self.confluence_id,
            "reference_price": self.reference_price,
            "no_trade_reason": self.no_trade_reason,
            "blocked_by": self.blocked_by,
        }

    @property
    def is_actionable_observation(self) -> bool:
        """A named direction (BUY / SELL) - an observation, never an order."""
        return self.direction in (OpportunityDirection.BUY.value, OpportunityDirection.SELL.value)


class SeriesOpportunities(BaseModel):
    symbol: str
    timeframe: str
    bars_analyzed: int = 0
    #: bar time of the last closed candle - the lifecycle is anchored on real bars
    last_bar_time: int | None = None
    confluences_considered: int = 0
    opportunities: list[Opportunity] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


def direction_for(confluence_direction: str) -> str:
    """Confluence vocabulary -> opportunity vocabulary (documented, 1:1)."""
    if confluence_direction == "BULLISH":
        return OpportunityDirection.BUY.value
    if confluence_direction == "BEARISH":
        return OpportunityDirection.SELL.value
    return OpportunityDirection.WATCH.value
