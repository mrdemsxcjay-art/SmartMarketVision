"""Centralised SMC / ICT parameters (Phase 4).

EVERY threshold used by the SMC/ICT engine lives here: no magic number is
scattered in the detectors. Values can be overridden from ``.env`` (prefix
``SMC_ICT_``) or at runtime through the API, so any detection is reproducible
from (OHLC + parameters).

Scale adaptivity
----------------
Absolute pip thresholds do not travel across instruments: EURUSD and GBPJPY do
not share volatility. Every "size-like" threshold is therefore the maximum of an
absolute floor in pips and a fraction of the ATR measured on the very same bars.
The ATR is computed from real OHLC, never estimated.

Vocabulary discipline
---------------------
Nothing here claims to know real orders. Liquidity is an *estimate* built from
geometry (``LIQUIDITY_POOL_ESTIMATE``): several touches of nearly the same price
level. No volume is ever invented - the provider does not supply it.

Confidence
----------
``confidence`` is the weighted share of the boolean criteria a detector really
evaluated. The weights are declared here; a criterion that was not evaluated
counts for nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# --------------------------------------------------------------------- weights
class SmcWeights(BaseModel):
    """Relative weight of each criterion family in the confidence."""

    structure: float = Field(default=2.0, ge=0.0, description="BOS / CHOCH / MSS")
    geometry: float = Field(default=1.5, ge=0.0, description="FVG, order block, dealing range")
    liquidity: float = Field(default=1.5, ge=0.0, description="equal levels, pool, sweep")
    displacement: float = Field(default=1.0, ge=0.0, description="impulse quality")
    context: float = Field(default=1.0, ge=0.0, description="premium / discount position")


# ---------------------------------------------------------------------- global
class SmcGlobalParams(BaseModel):
    """Window and pivot settings shared by every detector.

    The pivot definition is the one already used by Phase 1/2
    (:func:`app.services.structure.find_swings`): a pivot high needs ``high[i]``
    strictly greater than the ``left`` bars before and the ``right`` bars after.
    Strict inequality means equal highs produce NO pivot - which is exactly why
    equal-high detection is a separate detector and not a pivot variant.
    """

    pivot_left: int = Field(default=2, ge=1, le=10, description="Bars left of a pivot")
    pivot_right: int = Field(default=2, ge=1, le=10, description="Bars right of a pivot (confirmation delay)")
    window_bars: int = Field(default=300, ge=60, le=2000, description="Closed bars analysed per run")
    min_bars_required: int = Field(default=60, ge=20, description="Below this, nothing is attempted")
    atr_period: int = Field(default=14, ge=5, le=100)
    atr_slow_period: int = Field(default=100, ge=20, le=1000, description="Structural volatility scale")
    max_swings: int = Field(default=40, ge=6, description="Most recent swings kept for structure reads")
    max_tracked: int = Field(default=400, ge=10, description="Hard cap on tracked objects")
    pip_fallback: float = Field(default=0.0001, description="Used when the symbol has no catalog entry")
    scan_bars: int = Field(default=12, ge=1, description="Newest bars scanned per run")
    structure_bars: int = Field(
        default=200,
        ge=12,
        description="Structure history used to anchor long-lived objects (order blocks, breakers)",
    )


# --------------------------------------------------------------- swing strength
class SwingStrengthParams(BaseModel):
    """How a swing's ``strength`` is measured (integer, reproducible).

    ``strength`` counts how many bars on both sides the pivot dominates and how
    many ATRs it stands out from its neighbours; a flat market yields 0, a clean
    swing yields a higher integer. It is never an arbitrary score.
    """

    dominance_bars: int = Field(default=4, ge=1, description="Bars each side inspected for dominance")
    atr_scale: float = Field(default=0.5, ge=0.1, description="One strength point per this ATR of prominence")


# ------------------------------------------------------------------------- BOS
class BosParams(BaseModel):
    """Break of structure.

    A BOS is a CLOSE beyond the last confirmed swing in the direction of the
    prevailing structure: the body closes past the level. A mere wick is
    rejected unless ``allow_wick_break`` is explicitly raised, and even then the
    wick must exceed the level by ``wick_buffer_pips``.
    """

    allow_wick_break: bool = Field(default=False, description="Off: a wick alone is NOT a BOS")
    wick_buffer_pips: float = Field(default=1.0, ge=0.0, description="Extra distance a wick must clear")
    min_break_pips: float = Field(default=1.0, ge=0.0, description="Absolute floor beyond the level")
    min_break_atr: float = Field(default=0.05, ge=0.0, description="ATR fraction beyond the level")
    max_bars_since_swing: int = Field(default=80, ge=3, description="Stale swings cannot be broken")
    require_close: bool = Field(default=True, description="The candle must close past the level")


# ----------------------------------------------------------------------- CHOCH
class ChochParams(BaseModel):
    """Change of character: the prevailing structure is broken the other way.

    A CHOCH needs (1) a prevailing direction, and (2) a close beyond the swing
    that defined that direction. The swing that is broken is returned explicitly
    (``broken_swing``), as is the candle that confirmed it.
    """

    min_swings_for_trend: int = Field(default=3, ge=2, description="Swings needed before a direction exists")
    min_break_pips: float = Field(default=1.0, ge=0.0)
    min_break_atr: float = Field(default=0.05, ge=0.0)
    max_bars_since_swing: int = Field(default=80, ge=3)


# ------------------------------------------------------------------------- MSS
class MssParams(BaseModel):
    """Market structure shift.

    DEFINITION USED (single, non-negotiable - never combined with another):
    an MSS is a CHOCH that is immediately followed by a *displacement* candle in
    the new direction, i.e. a close beyond the CHOCH level by at least
    ``min_displacement_atr`` ATR with a body/range ratio of at least
    ``min_body_ratio``. A CHOCH without displacement stays a CHOCH and is never
    relabelled: MSS is a strict superset test applied to a confirmed CHOCH.
    """

    min_displacement_atr: float = Field(default=0.8, ge=0.0, description="Close beyond the CHOCH level")
    min_body_ratio: float = Field(default=0.5, ge=0.0, le=1.0, description="Body/range of the shift candle")
    max_bars_after_choch: int = Field(default=3, ge=1, description="Shift must follow quickly")


# ------------------------------------------------------------ equal high / low
class EqualLevelsParams(BaseModel):
    """Equal highs / equal lows: several swings at nearly the same price."""

    tolerance_pips: float = Field(default=3.0, ge=0.0, description="Absolute floor of the equality band")
    tolerance_atr: float = Field(default=0.15, ge=0.0, description="ATR fraction of the equality band")
    min_touches: int = Field(default=2, ge=2, le=10, description="Touches required to speak of equality")
    min_separation_bars: int = Field(default=3, ge=1, description="Two touches closer than this are one touch")
    max_separation_bars: int = Field(default=120, ge=5, description="The cluster must stay recent")


# ------------------------------------------------------------ liquidity pools
class LiquidityPoolParams(BaseModel):
    """Liquidity pool ESTIMATE.

    The engine cannot see real orders, so it never claims to: a pool is the
    geometric inference that resting liquidity is *likely* around a level that
    price touched repeatedly (equal highs / equal lows) or around an old swing
    that price never came back to. Hence the explicit name
    ``LIQUIDITY_POOL_ESTIMATE``.
    """

    use_equal_levels: bool = Field(default=True)
    use_old_swings: bool = Field(default=True)
    old_swing_min_bars: int = Field(default=20, ge=2, description="Age from which a swing counts as 'old'")
    max_pools: int = Field(default=12, ge=1, description="Strongest pools kept")
    max_pool_age_bars: int = Field(default=200, ge=5)


# ------------------------------------------------------------ liquidity sweep
class SweepParams(BaseModel):
    """Liquidity sweep: a level is pierced, then price closes back inside.

    Sequence enforced (all three steps are required):
      1. the candle's extreme goes BEYOND the level by at least
         ``min_penetration_pips`` / ``min_penetration_atr``;
      2. the same candle CLOSES back on the rejected side of the level
         (``reentry_buffer_pips`` in favour of the re-entry);
      3. the extreme is a genuine excursion (``min_wick_share`` of range).
    Without step 2 the event is NOT called a sweep - it is a break.
    """

    min_penetration_pips: float = Field(default=0.5, ge=0.0, description="How far past the level the extreme goes")
    min_penetration_atr: float = Field(default=0.05, ge=0.0)
    reentry_buffer_pips: float = Field(default=0.5, ge=0.0, description="Close must come back this far inside")
    min_wick_share: float = Field(default=0.4, ge=0.0, le=1.0, description="Excursion share of the candle range")
    max_level_age_bars: int = Field(default=120, ge=2, description="Stale levels cannot be swept")
    max_scan_bars: int = Field(default=6, ge=1, description="Newest bars inspected for a sweep")


# ------------------------------------------------------------------------- FVG
class FvgParams(BaseModel):
    """Fair value gap on three consecutive candles.

    A bullish FVG exists when ``low[i+2] > high[i]``: the middle candle moved so
    fast that a price band was never traded. The gap is the band
    ``[high[i], low[i+2]]``; a bearish gap is the mirror image
    (``high[i+2] < low[i]``, band ``[high[i+2], low[i]]``).

    The provider gives no volume, so the engine never claims the gap is
    "unfilled volume" - only that price did not trade that band.
    """

    min_size_pips: float = Field(default=1.0, ge=0.0, description="Absolute floor of the gap")
    min_size_atr: float = Field(default=0.10, ge=0.0, description="ATR fraction of the gap")
    max_gap_age_bars: int = Field(default=120, ge=3)
    max_scan_bars: int = Field(default=4, ge=1)
    max_tracked: int = Field(default=60, ge=1, description="Newest FVGs kept alive")


class MitigationParams(BaseModel):
    """FVG / order-block lifecycle thresholds.

    FVG_CREATED    : the gap was just formed.
    FVG_ACTIVE     : it survived at least ``activation_bars`` bars untouched.
    FVG_PARTIALLY_FILLED : price entered the band but did not cross it entirely.
    FVG_FILLED     : price crossed the whole band (see ``fill_rule``).
    """

    activation_bars: int = Field(default=1, ge=0, description="Bars without a touch before ACTIVE")
    partial_share: float = Field(default=0.5, ge=0.05, le=0.95, description="Share of the band that counts as partial")
    fill_rule: str = Field(default="full_traverse", description="full_traverse | close_beyond")
    expiry_bars: int = Field(default=200, ge=5)


# ------------------------------------------------------------------ order block
class OrderBlockParams(BaseModel):
    """Order block - deterministic definition (the only one used).

    An order block is the LAST OPPOSITE candle before a displacement that breaks
    structure. Concretely, for a bullish block:
      1. take the last bearish candle before a bullish BOS / MSS;
      2. require a displacement candle (>= ``min_displacement_atr`` ATR, body
         ratio >= ``min_body_ratio``) in the same move;
      3. the zone is the origin candle's full range [low, high], optionally
         narrowed to its body (``zone_from_body``);
      4. the distance between origin candle and break must stay under
         ``max_bars_to_break``.
    No vague "supply/demand area": every block carries its trigger event.
    """

    zone_from_body: bool = Field(default=False, description="Use the origin candle body instead of its full range")
    min_displacement_atr: float = Field(default=0.8, ge=0.0)
    min_body_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    max_bars_to_break: int = Field(default=8, ge=1, description="Origin candle -> structural break")
    max_block_age_bars: int = Field(default=150, ge=5)
    max_tracked: int = Field(default=40, ge=1)
    require_bos_or_mss: bool = Field(default=True, description="A block without a structural break is not a block")


# --------------------------------------------------------------- breaker block
class BreakerParams(BaseModel):
    """Breaker block: built FROM an existing order block, never detected alone.

    Explicit cycle: ORDER_BLOCK -> (price closes through the zone) INVALIDATION
    -> STRUCTURAL_BREAK (a BOS/CHOCH in the opposite direction) -> BREAKER.
    A block that is invalidated without a structural break stays INVALIDATED and
    is never promoted.
    """

    invalidation_close_buffer_pips: float = Field(default=0.5, ge=0.0)
    require_structural_break: bool = Field(default=True)
    max_bars_to_promote: int = Field(default=60, ge=1)


# --------------------------------------------------------------- displacement
class DisplacementParams(BaseModel):
    """Impulsive move, measured instead of felt.

    ``displacement_measure`` = the candle range expressed both in pips and in
    ATR, the body/range ratio, the progression of the close beyond the previous
    candle's extreme, the trace efficiency and the number of consecutive bars
    travelling the same way. A "big candle" is never enough: the numbers
    produced here are the ones shown in the UI.
    """

    min_range_atr: float = Field(default=1.2, ge=0.0, description="Range floor (ATR multiple)")
    min_range_pips: float = Field(default=8.0, ge=0.0, description="Range floor (absolute)")
    min_body_ratio: float = Field(default=0.55, ge=0.0, le=1.0)
    min_progression_atr: float = Field(
        default=0.5, ge=0.0, description="How far the close must take out the previous candle's extreme (ATR)"
    )
    min_progression_pips: float = Field(
        default=2.0, ge=0.0, description="How far the close must take out the previous candle's extreme (pips)"
    )
    lookback_bars: int = Field(default=6, ge=2, description="Consecutive bars considered one move")


# --------------------------------------------------------------- dealing range
class DealingRangeParams(BaseModel):
    """Dealing range selection (documented, never arbitrary).

    The range is built from the two most recent CONFIRMED swings that enclose
    price and are at least ``min_span_atr`` apart: the highest swing high and the
    lowest swing low within ``lookback_bars``. If no such pair exists, NO range
    is produced - the engine refuses to invent one just to print a
    premium/discount zone.
    """

    lookback_bars: int = Field(default=120, ge=10, description="Swings considered for the range")
    min_span_atr: float = Field(default=2.0, ge=0.0, description="Minimum height of a usable range")
    min_swings_each_side: int = Field(default=1, ge=1, description="Swings needed on each side")
    require_price_inside: bool = Field(default=True, description="Price must sit inside the range")


class PremiumDiscountParams(BaseModel):
    """Where price sits inside the dealing range (pure proportion)."""

    equilibrium_band: float = Field(default=0.02, ge=0.0, le=0.2, description="Half-width of the equilibrium band")
    premium_zone: float = Field(default=0.75, ge=0.5, le=1.0, description="Position above which price is premium")
    discount_zone: float = Field(default=0.25, ge=0.0, le=0.5, description="Position below which price is discount")


# -------------------------------------------------------------------- confluence
class SmcConfluenceParams(BaseModel):
    """Internal SMC/ICT confluence: descriptive only, never a score."""

    max_items_per_group: int = Field(default=12, ge=1)
    max_bars_between: int = Field(default=40, ge=2, description="Objects further apart are not related")
    require_same_direction: bool = Field(default=True, description="A bull and a bear object are not confluent")
    trading_signal: bool = Field(default=False, frozen=True, description="SMC context is NEVER a trading signal")


# -------------------------------------------------------------------------- hub
class SmcIctParams(BaseSettings):
    """Runtime parameters of the SMC/ICT engine (``SMC_ICT_`` env prefix)."""

    model_config = SettingsConfigDict(env_prefix="SMC_ICT_", env_file=".env", extra="ignore")

    enabled: bool = Field(default=True)
    run_on: str = Field(default="scanner", description="scanner | manual")

    global_: SmcGlobalParams = Field(default_factory=SmcGlobalParams)
    swings: SwingStrengthParams = Field(default_factory=SwingStrengthParams)
    bos: BosParams = Field(default_factory=BosParams)
    choch: ChochParams = Field(default_factory=ChochParams)
    mss: MssParams = Field(default_factory=MssParams)
    equal_levels: EqualLevelsParams = Field(default_factory=EqualLevelsParams)
    pools: LiquidityPoolParams = Field(default_factory=LiquidityPoolParams)
    sweep: SweepParams = Field(default_factory=SweepParams)
    fvg: FvgParams = Field(default_factory=FvgParams)
    mitigation: MitigationParams = Field(default_factory=MitigationParams)
    order_block: OrderBlockParams = Field(default_factory=OrderBlockParams)
    breaker: BreakerParams = Field(default_factory=BreakerParams)
    displacement: DisplacementParams = Field(default_factory=DisplacementParams)
    dealing_range: DealingRangeParams = Field(default_factory=DealingRangeParams)
    premium_discount: PremiumDiscountParams = Field(default_factory=PremiumDiscountParams)
    confluence: SmcConfluenceParams = Field(default_factory=SmcConfluenceParams)
    weights: SmcWeights = Field(default_factory=SmcWeights)

    #: group order used by the API and the dashboard
    GROUPS: tuple[str, ...] = (
        "globals",
        "swings",
        "bos",
        "choch",
        "mss",
        "equal_levels",
        "pools",
        "sweep",
        "fvg",
        "mitigation",
        "order_block",
        "breaker",
        "displacement",
        "dealing_range",
        "premium_discount",
        "confluence",
        "weights",
    )

    def snapshot(self) -> dict[str, Any]:
        """Flat, JSON-serialisable view: ``{group: {key: value}}``.

        ``global_`` is exposed as ``globals`` for the API, exactly like the
        Phase 2/3 parameter endpoints.
        """
        out: dict[str, Any] = {}
        for name in self.GROUPS:
            attribute = "global_" if name == "globals" else name
            if not hasattr(self, attribute):
                continue
            value = getattr(self, attribute)
            if isinstance(value, BaseModel):
                out["globals" if attribute == "global_" else attribute] = value.model_dump()
            else:
                out[attribute] = value
        return out


#: shared default instance (overridable at runtime through the API)
params = SmcIctParams()
