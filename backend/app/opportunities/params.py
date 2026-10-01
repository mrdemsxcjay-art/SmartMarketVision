"""Centralised Opportunity Engine parameters (Phase 6).

EVERY threshold used by the opportunity engine lives here (``OPPORTUNITY_`` env
prefix, overridable at runtime through the API). No magic number is hidden in the
code.

What an opportunity IS
----------------------
The analytical direction observed when a confluence is strong enough: ``BUY`` and
``SELL`` are directions **observed**, exactly like ``BULLISH`` / ``BEARISH`` in
the other engines - the vocabulary was requested in those exact terms, and it
changes nothing to the nature of the system. There is no broker, no order, no
position: the engine cannot do anything else than write a row and publish an
event.

What the opportunity score IS
-----------------------------
A separate, explicable count of the criteria that were really checked (structure,
liquidity, imbalance, trigger, displacement, confluence level). It is NOT a
probability of success and must never be presented as one.

Anti-spam
---------
One stable key per observation (pair + timeframe + direction + the structure
events that carry it) plus a cooldown: the same observation cannot produce two
identical alerts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpportunityConditions(BaseModel):
    """What must be true before a direction may be named (6.2)."""

    required_dimensions: tuple[str, ...] = Field(
        default=("STRUCTURE",),
        description="Dimensions that MUST be present (structure is the backbone of a direction)",
    )
    min_dimensions: int = Field(default=4, ge=1, le=8, description="Distinct dimensions required")
    min_score: float = Field(default=7.0, ge=0.0, le=10.0, description="Opportunity score required")
    min_events: int = Field(default=3, ge=1, le=24, description="Distinct source detections required")
    max_contradictions: int = Field(
        default=0, ge=0, le=8, description="A BUY / SELL is refused as soon as a major reading opposes it"
    )
    watch_score: float = Field(
        default=5.0, ge=0.0, le=10.0, description="From here a WATCH observation is reported"
    )
    min_atr_ratio: float = Field(
        default=2e-5,
        ge=0.0,
        description=(
            "Minimum ATR expressed as a fraction of price (instrument agnostic). "
            "2e-5 = 0.002%: only a market that is essentially frozen in its own price "
            "scale is refused, and an ATR of exactly 0 is always refused."
        ),
    )
    max_age_bars: int = Field(
        default=24, ge=2, le=500, description="The confluence anchor older than this is refused"
    )


class OpportunityWeights(BaseModel):
    """Points of the opportunity score (sum = maximum, 10 by default)."""

    structure: float = Field(default=3.0, ge=0.0, le=10.0, description="structure aligned with the direction")
    liquidity: float = Field(default=2.0, ge=0.0, le=10.0, description="liquidity reading present")
    imbalance: float = Field(default=1.5, ge=0.0, le=10.0, description="FVG / order block present")
    trigger: float = Field(default=1.5, ge=0.0, le=10.0, description="price-action trigger present")
    displacement: float = Field(default=1.0, ge=0.0, le=10.0, description="displacement present")
    confluence_level: float = Field(default=1.0, ge=0.0, le=10.0, description="confluence state at least CONFLUENCE")


class OpportunityLifecycle(BaseModel):
    """Validity and anti-spam (6.5, 6.6)."""

    validity_bars: int = Field(default=30, ge=2, le=1000, description="Lifetime of an opportunity")
    confirm_bars: int = Field(
        default=3, ge=1, le=100, description="Bars allowed for a confirmation close (observation, not a trade)"
    )
    cooldown_seconds: int = Field(
        default=900, ge=0, description="Minimum delay between two alerts for the same observation"
    )
    notify_states: tuple[str, ...] = Field(
        default=("CREATED", "CONFIRMED", "INVALIDATED", "EXPIRED"),
        description="States worth an alert (the outbox decides how to deliver it)",
    )
    max_tracked: int = Field(default=200, ge=10)
    min_bars_required: int = Field(default=60, ge=20)
    atr_period: int = Field(default=14, ge=5, le=100)
    pip_fallback: float = Field(default=0.0001)


class OpportunityParams(BaseSettings):
    """Runtime parameters of the opportunity engine (``OPPORTUNITY_`` prefix)."""

    model_config = SettingsConfigDict(env_prefix="OPPORTUNITY_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=True)
    run_on: str = Field(default="scanner", description="scanner | manual")

    conditions: OpportunityConditions = Field(default_factory=OpportunityConditions)
    weights: OpportunityWeights = Field(default_factory=OpportunityWeights)
    lifecycle: OpportunityLifecycle = Field(default_factory=OpportunityLifecycle)

    #: group order used by the API and the dashboard
    GROUPS: tuple[str, ...] = ("conditions", "weights", "lifecycle")

    def max_score(self) -> float:
        weights = self.weights
        return float(
            weights.structure
            + weights.liquidity
            + weights.imbalance
            + weights.trigger
            + weights.displacement
            + weights.confluence_level
        )

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.GROUPS:
            value = getattr(self, name, None)
            if isinstance(value, BaseModel):
                out[name] = value.model_dump()
        out["derived"] = {"max_score": self.max_score()}
        return out

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> list[str]:
        applied: list[str] = []
        for group, values in (overrides or {}).items():
            target = getattr(self, group, None)
            if not isinstance(target, BaseModel):
                applied.append(f"ignored:{group}")
                continue
            for key, value in (values or {}).items():
                if key not in type(target).model_fields:
                    applied.append(f"ignored:{group}.{key}")
                    continue
                setattr(target, key, value)
                applied.append(f"{group}.{key}={value}")
        return applied


#: shared default instance (overridable at runtime through the API)
params = OpportunityParams()
