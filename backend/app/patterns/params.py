"""Centralised detection parameters.

EVERY threshold used by the chartist engine lives here: no magic number is
scattered in the detectors. Values can be overridden from ``.env`` (prefix
``PATTERN_``) or at runtime through the API, so a detection is always
reproducible from (OHLC + parameters).

Scale adaptivity
----------------
Absolute pip thresholds do not work across instruments (EURUSD and GBPJPY have
different volatility). Each "size-like" threshold is therefore the maximum of an
absolute floor in pips and a fraction of the ATR(period) measured on the very
same bars. The ATR is computed from real OHLC, never estimated.

Confidence
----------
``confidence`` is a weighted sum of the boolean criteria listed by each detector.
The weights are declared here; any criterion not declared contributes nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GlobalParams(BaseModel):
    """Window and pivot settings shared by every detector."""

    pivot_left: int = Field(default=2, ge=1, le=10, description="Bars left of a pivot")
    pivot_right: int = Field(default=2, ge=1, le=10, description="Bars right of a pivot (confirmation delay)")
    window_bars: int = Field(default=300, ge=60, le=2000, description="Closed bars analysed per run")
    min_bars_required: int = Field(default=60, ge=20, description="Below this, no detection is attempted")
    atr_period: int = Field(default=14, ge=5, le=100)
    atr_slow_period: int = Field(
        default=100, ge=20, le=1000, description="Structural volatility scale used to size patterns"
    )
    max_pivots: int = Field(default=40, ge=6, description="Most recent pivots kept for analysis")
    pip_fallback: float = Field(default=0.0001, description="Used when the symbol has no catalog entry")


class DoubleTopBottomParams(BaseModel):
    min_peak_separation_bars: int = Field(default=5, ge=2)
    max_peak_separation_bars: int = Field(default=120, ge=10)
    peak_tolerance_pips: float = Field(default=5.0, ge=0.0, description="Absolute floor")
    peak_tolerance_atr: float = Field(default=0.5, ge=0.0, description="ATR fraction floor")
    min_valley_depth_pips: float = Field(default=8.0, ge=0.0)
    min_valley_depth_atr: float = Field(default=1.0, ge=0.0)
    min_valley_depth_ratio: float = Field(
        default=0.2, ge=0.0, le=0.9,
        description="The reaction must retrace at least this share of the prior advance",
    )
    prior_lookback_bars: int = Field(default=60, ge=5, description="Lookback used to measure the prior advance")
    symmetry_max_ratio: float = Field(default=3.0, ge=1.0, description="Max ratio between the two half-spans")
    forbid_intervening_extreme: bool = Field(
        default=True, description="Reject if another pivot exceeds both peaks between them"
    )
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    invalidation_buffer_pips: float = Field(default=2.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=60, ge=1, description="After this, the pattern expires")
    max_bars_since_formation: int = Field(
        default=60, ge=1, description="The second extreme must be this recent to be signalled"
    )


class HeadShouldersParams(BaseModel):
    shoulder_tolerance_pips: float = Field(default=8.0, ge=0.0)
    shoulder_tolerance_atr: float = Field(default=0.8, ge=0.0)
    head_min_prominence_pips: float = Field(default=6.0, ge=0.0)
    head_min_prominence_atr: float = Field(default=0.6, ge=0.0)
    min_valley_depth_pips: float = Field(default=8.0, ge=0.0)
    min_valley_depth_atr: float = Field(default=1.0, ge=0.0)
    neckline_max_slope_atr_per_bar: float = Field(default=0.25, ge=0.0)
    max_total_bars: int = Field(default=160, ge=20)
    require_trend_context: bool = Field(
        default=True, description="An H&S must follow a real advance (and the inverse a fall)"
    )
    trend_lookback_bars: int = Field(default=40, ge=5, description="Bars scanned before the left shoulder")
    trend_min_atr: float = Field(default=2.0, ge=0.0)
    trend_min_pips: float = Field(default=25.0, ge=0.0)
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    invalidation_buffer_pips: float = Field(default=2.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=80, ge=1)
    max_bars_since_formation: int = Field(
        default=80, ge=1, description="The right shoulder must be this recent to be signalled"
    )


class TriangleParams(BaseModel):
    min_touches_per_line: int = Field(
        default=3, ge=2, description="A triangle is never declared from two points per line"
    )
    min_total_touches: int = Field(default=5, ge=3)
    touch_tolerance_pips: float = Field(default=5.0, ge=0.0)
    touch_tolerance_atr: float = Field(default=0.5, ge=0.0)
    flat_slope_atr_per_bar: float = Field(
        default=0.02, ge=0.0, description="Below this (in ATR per bar) a boundary counts as horizontal"
    )
    min_width_contraction: float = Field(
        default=0.30, ge=0.05, le=0.95, description="Width contraction required across the formation"
    )
    convergence_required: bool = True
    min_width_pips: float = Field(default=25.0, ge=0.0, description="Minimum width of the formation")
    min_width_atr: float = Field(default=1.5, ge=0.0)
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=60, ge=1)


class WedgeParams(BaseModel):
    min_width_pips: float = Field(default=25.0, ge=0.0, description="Minimum width of the wedge")
    min_width_atr: float = Field(default=1.5, ge=0.0)
    min_touches_per_line: int = Field(default=3, ge=2)
    min_total_touches: int = Field(default=6, ge=3)
    touch_tolerance_pips: float = Field(default=5.0, ge=0.0)
    touch_tolerance_atr: float = Field(default=0.5, ge=0.0)
    flat_slope_atr_per_bar: float = Field(
        default=0.02, ge=0.0, description="Below this (in ATR per bar) a boundary counts as horizontal"
    )
    min_width_contraction: float = Field(
        default=0.25, ge=0.05, le=0.95, description="Width contraction required across the wedge"
    )
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=60, ge=1)


class RectangleParams(BaseModel):
    min_touches_per_side: int = Field(default=2, ge=2)
    horizontal_tolerance_pips: float = Field(default=8.0, ge=0.0)
    horizontal_tolerance_atr: float = Field(default=0.6, ge=0.0)
    min_height_pips: float = Field(default=12.0, ge=0.0)
    min_height_atr: float = Field(default=1.2, ge=0.0)
    min_bars: int = Field(default=12, ge=4)
    max_bars: int = Field(default=200, ge=10)
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=60, ge=1)


class FlagPennantParams(BaseModel):
    impulse_min_atr: float = Field(default=2.0, ge=0.5, description="Pole size as a multiple of ATR")
    impulse_min_pips: float = Field(default=25.0, ge=0.0)
    impulse_max_bars: int = Field(default=30, ge=3)
    consolidation_min_bars: int = Field(default=5, ge=2)
    consolidation_max_bars: int = Field(default=60, ge=5)
    max_retrace_ratio: float = Field(default=0.6, ge=0.1, le=1.0, description="Max retracement of the pole")
    max_width_atr: float = Field(
        default=2.0, ge=0.2, description="Consolidation width vs the ATR measured over the pole"
    )
    max_width_pole_ratio: float = Field(
        default=0.5, ge=0.05, le=1.0, description="Consolidation width vs the size of the pole"
    )
    parallel_tolerance: float = Field(default=0.35, ge=0.0, description="Relative slope difference for a FLAG")
    min_contraction: float = Field(
        default=0.20, ge=0.02, le=0.95, description="Width contraction required for a PENNANT"
    )
    max_box_drift_ratio: float = Field(
        default=0.5, ge=0.05, description="Box drift over the consolidation vs its own width"
    )
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)
    max_bars_to_confirm: int = Field(default=40, ge=1)


class LevelParams(BaseModel):
    cluster_tolerance_pips: float = Field(default=6.0, ge=0.0)
    cluster_tolerance_atr: float = Field(default=0.5, ge=0.0)
    min_touches: int = Field(default=2, ge=2)
    max_levels: int = Field(default=6, ge=1)
    reaction_min_atr: float = Field(default=0.5, ge=0.0, description="Reaction needed to count as a rejection")
    max_closes_beyond: int = Field(
        default=1, ge=0, description="Closed bars allowed beyond the level before it is considered stale"
    )
    max_bars_since_touch: int = Field(
        default=60, ge=1, description="A level untouched for longer than this is no longer a live level"
    )


class ChannelParams(BaseModel):
    min_touches_per_line: int = Field(default=3, ge=2)
    min_total_touches: int = Field(default=6, ge=3)
    touch_tolerance_pips: float = Field(default=6.0, ge=0.0)
    touch_tolerance_atr: float = Field(default=0.6, ge=0.0)
    parallel_tolerance: float = Field(default=0.35, ge=0.0, description="|slope_up - slope_low| / max|slope|")
    flat_slope_atr_per_bar: float = Field(
        default=0.02, ge=0.0, description="Below this (in ATR per bar) the channel counts as a rectangle"
    )
    max_width_drift: float = Field(default=0.5, ge=0.0, description="Max relative width change along the channel")
    min_width_atr: float = Field(default=0.8, ge=0.0)
    confirmation_buffer_pips: float = Field(default=1.0, ge=0.0)


class BreakoutParams(BaseModel):
    buffer_pips: float = Field(default=1.0, ge=0.0, description="Close must clear the level by this much")
    require_close: bool = Field(default=True, description="A wick alone is never a breakout")
    max_bars_after_formation: int = Field(default=80, ge=1)
    retest_tolerance_pips: float = Field(default=3.0, ge=0.0)
    retest_max_bars: int = Field(default=30, ge=1)
    retest_min_distance_pips: float = Field(default=0.0, ge=0.0)


class ConfidenceWeights(BaseModel):
    """Weights used by every detector (identical scale = comparable scores)."""

    structure_clear: float = Field(default=1.0, description="Pattern geometry unambiguous")
    level_quality: float = Field(default=1.0, description="Reaction depth / touch quality")
    symmetry: float = Field(default=1.0, description="Temporal and price symmetry")
    volume_or_time: float = Field(default=1.0, description="Formation duration inside ideal band")
    no_conflict: float = Field(default=1.0, description="No conflicting pivot / structure")
    breakout: float = Field(default=1.0, description="Breakout already confirmed")


class PatternParams(BaseSettings):
    """Full parameter set of the chartist engine."""

    model_config = SettingsConfigDict(env_prefix="PATTERN_", env_file=".env", extra="ignore")

    enabled: bool = True
    run_on: str = Field(default="CLOSED_CANDLES_ONLY", description="Informational: the engine never uses the forming bar")
    dedup_cooldown_bars: int = Field(default=5, ge=0, description="Same formation re-announcement guard")

    # per-family parameters (grouped, defaults above)
    global_: GlobalParams = Field(default_factory=GlobalParams)
    double_top_bottom: DoubleTopBottomParams = Field(default_factory=DoubleTopBottomParams)
    head_shoulders: HeadShouldersParams = Field(default_factory=HeadShouldersParams)
    triangle: TriangleParams = Field(default_factory=TriangleParams)
    wedge: WedgeParams = Field(default_factory=WedgeParams)
    rectangle: RectangleParams = Field(default_factory=RectangleParams)
    flags: FlagPennantParams = Field(default_factory=FlagPennantParams)
    levels: LevelParams = Field(default_factory=LevelParams)
    channel: ChannelParams = Field(default_factory=ChannelParams)
    breakout: BreakoutParams = Field(default_factory=BreakoutParams)
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

    @property
    def globals(self) -> GlobalParams:  # convenience alias ("globals" is a keyword-ish name)
        return self.global_

    def snapshot(self) -> dict[str, Any]:
        """Full parameter set, safe to persist with every detection.

        The ``global_`` field (renamed to dodge the ``global`` keyword) is exposed
        as ``globals`` so the API, the dashboard and the stored detections all use
        the same vocabulary.
        """
        data = self.model_dump(mode="json")
        if "global_" in data:
            data["globals"] = data.pop("global_")
        return data


#: process-wide parameter set (overridable in tests / through the API)
params = PatternParams()
