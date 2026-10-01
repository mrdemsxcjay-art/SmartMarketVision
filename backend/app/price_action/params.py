"""PHASE 3 - Price Action engine: the ONLY place where its thresholds live.

Every threshold used by the price-action detectors is declared here, named,
documented and validated by pydantic, so a detection is always reproducible from
(real OHLC + these parameters). Overridable from ``.env`` (prefix
``PRICE_ACTION_``) and at runtime through ``PATCH /api/price-action/params``.

Scale adaptivity
----------------
Like the chartist engine, every "size-like" threshold is the maximum of an
absolute floor **in pips** and a fraction of the ATR measured on the very same
bars: a 3-pip pin bar is meaningful on EURUSD M15 and meaningless on GBPJPY H4.

What this engine never does
---------------------------
No vague reading ("it looks like a hammer"), no trading signal (BUY/SELL/ENTRY/
SL/TP are absent from the whole vocabulary), no invented volume, no synthetic
price. A detection is a set of boolean criteria that a human can re-check by hand
bar by bar - and ``confidence`` is exactly the weighted share of them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PriceActionWeights(BaseModel):
    """Confidence weights (same scale for every price-action detector)."""

    candle_geometry: float = Field(default=1.5, description="Candle body/wick geometry is unambiguous")
    relative_size: float = Field(default=1.0, description="Candle size compared with recent volatility")
    level_context: float = Field(default=1.0, description="Pattern sits on a real level (S/R, breakout level)")
    pattern_context: float = Field(default=1.0, description="Pattern relates to an active chartist formation")
    confirmation: float = Field(default=1.0, description="Confirmation candle already closed beyond the trigger")
    no_conflict: float = Field(default=1.0, description="No opposing candle inside the pattern window")
    structure_clear: float = Field(default=1.0, description="Structural reading is explicit (move, box, failure)")
    symmetry: float = Field(default=1.0, description="The move / the candle is balanced, not one-sided noise")
    time_context: float = Field(default=1.0, description="Timing is meaningful (fresh event, representative window)")


class PriceActionGlobalParams(BaseModel):
    """Window and volatility settings shared by every price-action detector."""

    #: bars analysed per run: candlestick patterns are local, the whole history
    #: is useless and would only slow the scanner down
    scan_bars: int = Field(default=12, ge=1, le=200, description="Most recent closed bars scanned for a pattern")
    window_bars: int = Field(default=300, ge=60, le=2000, description="Closed bars kept in the analysis context")
    min_bars_required: int = Field(default=60, ge=20, description="Below this, no detection is attempted")
    atr_period: int = Field(default=14, ge=5, le=100, description="Current volatility (slope / wick sizing)")
    atr_slow_period: int = Field(default=100, ge=20, le=1000, description="Structural volatility scale")
    pip_fallback: float = Field(default=0.0001, description="Used when the symbol has no catalog entry")
    #: a candle pattern that is not confirmed quickly is dead: price has moved on
    max_bars_to_confirm: int = Field(default=12, ge=1, le=200, description="Confirmation window (bars)")
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0, description="Close must clear the level by this")
    invalidation_buffer_pips: float = Field(default=1.0, ge=0.0, description="Close beyond this cancels the pattern")
    max_tracked: int = Field(default=400, ge=10, description="Live formations kept per process")
    #: bars of context kept on each side of the pattern for the drawing / evidence
    context_bars: int = Field(default=3, ge=1, le=20)


class EngulfingParams(BaseModel):
    """Bullish / bearish engulfing: measurable body containment."""

    min_previous_body_pips: float = Field(default=1.0, ge=0.0, description="The engulfed body must exist")
    min_previous_body_atr: float = Field(default=0.05, ge=0.0)
    min_coverage: float = Field(
        default=1.0, ge=0.8, le=3.0,
        description="How much of the previous body the current body must cover (1.0 = full)",
    )
    min_body_multiple: float = Field(default=1.0, ge=0.5, description="Current body / previous body")
    min_body_ratio: float = Field(default=0.45, ge=0.0, le=1.0, description="Current body / current range")
    max_opposite_wick_ratio: float = Field(
        default=0.45, ge=0.0, le=1.0,
        description="The wick opposite to the move must stay small, else the engulfing is not clean",
    )
    require_direction_change: bool = Field(
        default=True, description="Previous candle must point the other way (bearish before a bullish engulfing)"
    )
    min_candle_range_pips: float = Field(default=2.0, ge=0.0, description="Anti-noise floor")
    min_candle_range_atr: float = Field(default=0.35, ge=0.0)


class PinBarParams(BaseModel):
    """Pin bar: a long *dominant* wick, a small body, put at the right end.

    A long wick alone is never enough: the opposite wick must be small, the body
    must sit at the opposite end of the range, and the candle must be big enough
    compared with the current volatility to mean anything.
    """

    min_wick_body_ratio: float = Field(default=2.0, ge=1.0, description="Dominant wick / body")
    min_wick_range_ratio: float = Field(default=0.6, ge=0.3, le=1.0, description="Dominant wick / range")
    max_opposite_wick_ratio: float = Field(default=0.15, ge=0.0, le=0.5, description="Other wick / range")
    max_body_ratio: float = Field(default=0.35, ge=0.05, le=1.0, description="Body / range")
    body_position_min: float = Field(
        default=0.6, ge=0.5, le=1.0,
        description="Body must sit in this share of the range, measured from the wick side",
    )
    min_range_pips: float = Field(default=4.0, ge=0.0, description="Anti-noise floor")
    min_range_atr: float = Field(default=0.6, ge=0.0)


class HammerParams(PinBarParams):
    """Hammer / shooting star: the very same pin-bar geometry, **plus a context**.

    The geometry is inherited from :class:`PinBarParams` (the two must never drift
    apart), and what makes it a hammer is that it appears after a measurable
    decline - or advance, for a shooting star. A pin bar in the middle of a range
    is just a pin bar.
    """

    max_opposite_wick_ratio: float = Field(default=0.12, ge=0.0, le=0.5)
    context_lookback_bars: int = Field(default=8, ge=3, le=60)
    context_min_move_atr: float = Field(default=0.8, ge=0.0, description="Prior decline/advance required")
    context_min_move_pips: float = Field(default=5.0, ge=0.0)


class InsideBarParams(BaseModel):
    """Inside bar: the range is contained inside the mother bar's range."""

    max_range_ratio: float = Field(default=0.9, gt=0.0, le=1.0, description="Inside range / mother range")
    containment_tolerance_pips: float = Field(
        default=0.0, ge=0.0, description="Tolerated breach of the mother range (0 = strictly inside)"
    )
    min_mother_range_pips: float = Field(default=4.0, ge=0.0, description="Anti-noise floor")
    min_mother_range_atr: float = Field(default=0.6, ge=0.0)


class OutsideBarParams(BaseModel):
    """Outside bar: the range expands beyond the previous bar on both sides."""

    min_breach_pips: float = Field(default=0.5, ge=0.0, description="How far each side must be exceeded")
    min_range_ratio: float = Field(default=1.1, ge=1.0, description="Outside range / previous range")
    min_range_pips: float = Field(default=4.0, ge=0.0)
    min_range_atr: float = Field(default=0.6, ge=0.0)


class DojiParams(BaseModel):
    """Doji: a small body **relative to the range**, never Open == Close."""

    max_body_ratio: float = Field(default=0.1, ge=0.0, le=0.5, description="Body / range")
    min_range_pips: float = Field(default=3.0, ge=0.0, description="A flat candle with no range is not a doji")
    min_range_atr: float = Field(default=0.5, ge=0.0)
    long_legged_wick_ratio: float = Field(
        default=0.3, ge=0.05, le=0.5, description="Both wicks above this share of the range = long-legged"
    )


class StructureContextParams(BaseModel):
    """Structural price-action events: impulse, consolidation, rejection."""

    # ---- impulse: a contiguous directional run, anchored on its first bar so the
    # same move keeps the same identity from one run to the next
    impulse_max_lookback_bars: int = Field(default=24, ge=2, le=200, description="How far back the run may start")
    impulse_min_bars: int = Field(default=4, ge=2, le=50, description="Bars aligned in the same direction")
    impulse_min_move_atr: float = Field(default=1.5, ge=0.2, description="Net move / ATR")
    impulse_min_move_pips: float = Field(default=15.0, ge=0.0)
    impulse_min_efficiency: float = Field(
        default=0.8, ge=0.1, le=1.0,
        description="Net move / sum of absolute bar-to-bar moves (a clean move, not a chop)",
    )
    impulse_max_pullback_ratio: float = Field(
        default=0.4, ge=0.0, le=1.0, description="Maximum adverse excursion inside the run (share of the move)"
    )

    # ---- consolidation: containment anchored on the first bar of the current
    # inside-the-box run, so a still-holding box keeps one single identity
    consolidation_box_bars: int = Field(default=10, ge=3, le=200, description="Bars defining the box")
    consolidation_window_bars: int = Field(default=20, ge=3, le=200, description="Maximum lookback of the box")
    consolidation_min_bars: int = Field(default=5, ge=2, le=200, description="Containment must last this long")
    consolidation_reference_bars: int = Field(default=40, ge=10, le=400, description="Volatility reference before the box")
    consolidation_max_compression: float = Field(
        default=0.6, ge=0.05, le=1.0, description="Mean range / reference mean range must stay below this"
    )
    consolidation_max_height_atr: float = Field(default=1.5, ge=0.1, description="Box height / ATR")
    consolidation_tolerance_pips: float = Field(default=1.0, ge=0.0, description="Containment tolerance")

    # ---- rejection of a real level
    rejection_level_tolerance_pips: float = Field(default=2.0, ge=0.0, description="Wick must reach the level")
    rejection_level_tolerance_atr: float = Field(default=0.25, ge=0.0)
    rejection_min_close_distance_pips: float = Field(default=3.0, ge=0.0, description="Close must move away")
    rejection_min_wick_range_ratio: float = Field(default=0.5, ge=0.2, le=1.0)
    rejection_max_bars_after_touch: int = Field(default=1, ge=0, le=5, description="Reaction must be immediate")

    # ---- failed breakout (consumes the Phase 2 breakout mechanism)
    failed_breakout_max_bars_to_fail: int = Field(default=20, ge=1, le=200)
    failed_breakout_min_return_pips: float = Field(
        default=1.0, ge=0.0, description="Close must be back beyond the level by this much"
    )


class LevelContextParams(BaseModel):
    """Relations between a candle pattern and real levels / formations."""

    proximity_pips: float = Field(default=6.0, ge=0.0, description="Absolute floor")
    proximity_atr: float = Field(default=0.5, ge=0.0, description="ATR fraction floor")
    zone_tolerance_pips: float = Field(default=8.0, ge=0.0, description="Rectangle / channel boundaries")
    context_band_atr: float = Field(
        default=5.0, ge=0.0,
        description="Levels further than this ATR band outside the observed price range are ignored",
    )
    zone_tolerance_atr: float = Field(default=0.7, ge=0.0)
    #: how many bars back a level may have been touched to stay "current"
    max_level_age_bars: int = Field(default=80, ge=5, le=1000)
    context_labels: bool = Field(
        default=True, description="Expose readable labels such as BULLISH_ENGULFING_AT_SUPPORT"
    )


class ConfluenceParams(BaseModel):
    """Confluence grouping (informative only: no score, no signal)."""

    enabled: bool = Field(default=True)
    window_bars: int = Field(default=10, ge=1, le=200, description="Events must be this close in time to be grouped")
    #: never exposed as a recommendation - the API says it explicitly
    trading_signal: bool = Field(default=False)


class PriceActionParams(BaseSettings):
    """Full parameter set of the price-action engine."""

    model_config = SettingsConfigDict(env_prefix="PRICE_ACTION_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=True)
    run_on: str = Field(
        default="CLOSED_CANDLES_ONLY", description="Informational: the engine never uses the forming bar"
    )

    global_: PriceActionGlobalParams = Field(default_factory=PriceActionGlobalParams)
    engulfing: EngulfingParams = Field(default_factory=EngulfingParams)
    pin_bar: PinBarParams = Field(default_factory=PinBarParams)
    hammer: HammerParams = Field(default_factory=HammerParams)
    inside_bar: InsideBarParams = Field(default_factory=InsideBarParams)
    outside_bar: OutsideBarParams = Field(default_factory=OutsideBarParams)
    doji: DojiParams = Field(default_factory=DojiParams)
    structure: StructureContextParams = Field(default_factory=StructureContextParams)
    levels: LevelContextParams = Field(default_factory=LevelContextParams)
    confluence: ConfluenceParams = Field(default_factory=ConfluenceParams)
    weights: PriceActionWeights = Field(default_factory=PriceActionWeights)

    @property
    def globals(self) -> PriceActionGlobalParams:  # convenience alias ("globals" is keyword-ish)
        return self.global_

    def snapshot(self) -> dict[str, Any]:
        """Full parameter set, safe to persist with every detection."""
        data = self.model_dump(mode="json")
        if "global_" in data:
            data["globals"] = data.pop("global_")
        return data


#: process-wide parameter set (overridable in tests / through the API)
params = PriceActionParams()
