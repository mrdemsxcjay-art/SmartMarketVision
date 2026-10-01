"""Centralised Confluence Engine parameters (Phase 5).

EVERY threshold used by the confluence engine lives here: no magic number is
scattered in the code. Values can be overridden from ``.env`` (prefix
``CONFLUENCE_``) or at runtime through the API, so any confluence is reproducible
from (detections + parameters).

What the score IS
-----------------
The confluence score measures **how many independent readings of the market agree
at the same time**, on a 0..10 scale. It is NOT a probability of success, it is
not a forecast and it is not a trading signal. Every point is traceable to the
dimension that earned it (see :mod:`app.confluence.scoring`).

What the score is built from
----------------------------
One dimension = one independent *kind* of reading. A dimension earns its weight
**once**, whatever the number of events behind it: three fair value gaps are one
reading, not three. That is what makes the score comparable across instruments
and timeframes - and it is why the weight table below is the whole story.

Contradictions
--------------
An opposing reading costs points instead of earning them, and the loss is
reported like a gain (same traceability). Two contradictory structure readings are
enough to declare the context CONTRADICTED: the engine then says so instead of
averaging the two sides into a meaningless number.

Temporal alignment
------------------
Detections must be close in time (``window_bars``) and close in price
(``price_band_atr``) to belong to the same confluence. A detection older than
``max_age_bars`` is dropped, never revived just because a new one appeared.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------- global
class ConfluenceGlobalParams(BaseModel):
    """Window, temporal alignment and price proximity."""

    window_bars: int = Field(
        default=6,
        ge=2,
        le=100,
        description="Max bar distance between two events of the same confluence",
    )
    max_age_bars: int = Field(
        default=24,
        ge=2,
        le=500,
        description="An event older than this (in bars) never participates",
    )
    validity_bars: int = Field(
        default=30,
        ge=2,
        le=500,
        description="A confluence expires after this many bars without a fresh event",
    )
    price_band_atr: float = Field(
        default=1.5,
        ge=0.1,
        le=20.0,
        description="Max price distance between the events and their reference price, in ATR",
    )
    min_events: int = Field(default=2, ge=1, le=24, description="Below this, NO_CONFLUENCE")
    max_events: int = Field(default=12, ge=2, le=60, description="Kept events per confluence")
    max_tracked: int = Field(default=200, ge=10, description="Hard cap on tracked confluences")
    min_bars_required: int = Field(default=60, ge=20)
    atr_period: int = Field(default=14, ge=5, le=100)
    atr_slow_period: int = Field(default=100, ge=20, le=1000)
    pip_fallback: float = Field(default=0.0001)


# ---------------------------------------------------------------------- states
class ConfluenceStateParams(BaseModel):
    """Score borders that map a score to a state (documented, no hidden rule)."""

    watch_score: float = Field(default=3.0, ge=0.0, le=10.0, description="From here: WATCH")
    confluence_score: float = Field(default=5.0, ge=0.0, le=10.0, description="From here: CONFLUENCE")
    strong_score: float = Field(default=7.0, ge=0.0, le=10.0, description="From here: STRONG_CONFLUENCE")
    strong_min_dimensions: int = Field(
        default=4, ge=2, le=8, description="STRONG_CONFLUENCE also needs this many dimensions"
    )
    contradiction_penalty: float = Field(
        default=2.0,
        ge=0.0,
        le=10.0,
        description="Contradiction points from which the context is CONTRADICTED",
    )
    expected_per_dimension: float = Field(
        default=1.0,
        ge=0.1,
        description="Contradiction points charged per opposing dimension",
    )
    context_opposition_penalty: float = Field(
        default=2.0,
        ge=0.0,
        le=10.0,
        description=(
            "Points charged when a SLOWER timeframe reads the structure the other way: "
            "it contradicts the local reading on a larger scale, so it weighs more than "
            "a single local dimension"
        ),
    )


# --------------------------------------------------------------------- weights
class ConfluenceWeights(BaseModel):
    """Weight of each dimension, in points, on a 0..10 scale.

    The sum of the weights is the maximum reachable score, so the score is always
    comparable: earning a dimension is worth exactly what is written here.
    """

    structure: float = Field(default=2.0, ge=0.0, le=10.0, description="BOS / CHOCH / MSS")
    liquidity: float = Field(default=2.0, ge=0.0, le=10.0, description="pool estimate, sweep, equal levels")
    imbalance: float = Field(default=1.0, ge=0.0, le=10.0, description="FVG, order block, breaker")
    displacement: float = Field(default=1.0, ge=0.0, le=10.0, description="impulse / displacement")
    price_action: float = Field(default=1.0, ge=0.0, le=10.0, description="rejection, engulfing, pin bar, ...")
    chartiste: float = Field(default=1.0, ge=0.0, le=10.0, description="figures, levels, breakout, retest")
    premium_discount: float = Field(default=1.0, ge=0.0, le=10.0, description="position inside the dealing range")
    multi_timeframe: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="a higher timeframe reads the same direction",
    )

    #: dimensions that can create a contradiction when they oppose the group
    major: tuple[str, ...] = (
        "STRUCTURE",
        "LIQUIDITY",
        "IMBALANCE",
        "DISPLACEMENT",
        "PRICE_ACTION",
        "CHARTISTE",
    )


# --------------------------------------------------------------- multi timeframe
class ConfluenceMultiTimeframeParams(BaseModel):
    """Multi-timeframe aggregation (never mixes timeframes without saying so)."""

    enabled: bool = Field(default=True)
    higher_timeframes: tuple[str, ...] = Field(
        default=("M5", "M15", "H1", "H4", "D1"),
        description="Context timeframes, ordered from the fastest to the slowest",
    )
    context_timeframes: int = Field(
        default=2,
        ge=0,
        le=4,
        description="How many slower timeframes are read as context (M15 -> H1, H4)",
    )
    max_age_bars: int = Field(
        default=6,
        ge=1,
        le=100,
        description="Age (in CONTEXT bars) beyond which a context reading is ignored",
    )


# ------------------------------------------------------------------------ model
class ConfluenceParams(BaseSettings):
    """Runtime parameters of the confluence engine (``CONFLUENCE_`` env prefix)."""

    model_config = SettingsConfigDict(env_prefix="CONFLUENCE_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=True)
    run_on: str = Field(default="scanner", description="scanner | manual")

    global_: ConfluenceGlobalParams = Field(default_factory=ConfluenceGlobalParams)
    states: ConfluenceStateParams = Field(default_factory=ConfluenceStateParams)
    weights: ConfluenceWeights = Field(default_factory=ConfluenceWeights)
    multi_timeframe: ConfluenceMultiTimeframeParams = Field(default_factory=ConfluenceMultiTimeframeParams)

    #: group order used by the API and the dashboard
    GROUPS: tuple[str, ...] = ("globals", "states", "weights", "multi_timeframe")

    def max_score(self) -> float:
        """Highest reachable score: the sum of the dimension weights."""
        weights = self.weights
        return float(
            weights.structure
            + weights.liquidity
            + weights.imbalance
            + weights.displacement
            + weights.price_action
            + weights.chartiste
            + weights.premium_discount
            + weights.multi_timeframe
        )

    def snapshot(self) -> dict[str, Any]:
        """Flat, JSON-serialisable view: ``{group: {key: value}}``."""
        out: dict[str, Any] = {}
        for name in self.GROUPS:
            attribute = "global_" if name == "globals" else name
            value = getattr(self, attribute, None)
            if isinstance(value, BaseModel):
                out[name] = value.model_dump()
            elif value is not None:
                out[name] = value
        out["derived"] = {"max_score": self.max_score()}
        return out

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> list[str]:
        """Apply a partial override map (group -> key -> value), validated.

        Unknown groups / keys are reported and ignored: a typo can never silently
        change the engine behaviour.
        """
        applied: list[str] = []
        for group, values in (overrides or {}).items():
            attribute = "global_" if group in ("globals", "global_") else group
            target = getattr(self, attribute, None)
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
params = ConfluenceParams()
