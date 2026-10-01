"""Normalisation of the three engines into one common event format (5.1).

The existing engines are **not** touched: this module only *reads* the detections
they already publish and rewrites them into :class:`ConfluenceEvent`. Every field
comes from the detection itself - symbol, timeframe, pattern, direction, bar time,
status, evidence and the real price taken from the detection's own drawing.

Dimension map (documented, exhaustive)
--------------------------------------
The dimension is what the reading *is*, not which engine produced it. The map is
declared once, here, and is used to compute the score, so a point can always be
traced back to the exact pattern that earned it.

======================  ==========================  ==============================
Engine                  Pattern                     Dimension
======================  ==========================  ==============================
SMC_ICT                 BOS / CHOCH / MSS           STRUCTURE
SMC_ICT                 EQUAL_HIGH / EQUAL_LOW      LIQUIDITY
SMC_ICT                 LIQUIDITY_POOL_ESTIMATE     LIQUIDITY
SMC_ICT                 LIQUIDITY_SWEEP             LIQUIDITY
SMC_ICT                 *FVG                        IMBALANCE
SMC_ICT                 *ORDER_BLOCK / BREAKER      IMBALANCE
SMC_ICT                 DISPLACEMENT                DISPLACEMENT
SMC_ICT                 DEALING_RANGE / PREMIUM /   PREMIUM_DISCOUNT
                        DISCOUNT / EQUILIBRIUM
PRICE_ACTION            every pattern               PRICE_ACTION
CHARTISTE               every pattern               CHARTISTE
======================  ==========================  ==============================

Only the real production patterns are listed; an unknown pattern falls back to
the dimension of its own engine (see :data:`FALLBACK_DIMENSION`), is still counted
and is visible in the evidence: nothing is silently dropped.
"""

from __future__ import annotations

from app.confluence.models import ConfluenceDimension, ConfluenceEvent
from app.schemas.events import DetectionCategory, DetectionStatus, PatternDetection

FALLBACK_DIMENSION: dict[str, str] = {
    DetectionCategory.CHARTISTE.value: ConfluenceDimension.CHARTISTE.value,
    DetectionCategory.PRICE_ACTION.value: ConfluenceDimension.PRICE_ACTION.value,
    DetectionCategory.SMC_ICT.value: ConfluenceDimension.STRUCTURE.value,
}

#: exact pattern -> dimension (only patterns really produced by the engines)
PATTERN_DIMENSION: dict[str, str] = {
    # ---------------------------------------------------------------- SMC / ICT
    "BOS": ConfluenceDimension.STRUCTURE.value,
    "CHOCH": ConfluenceDimension.STRUCTURE.value,
    "MSS": ConfluenceDimension.STRUCTURE.value,
    "EQUAL_HIGH": ConfluenceDimension.LIQUIDITY.value,
    "EQUAL_LOW": ConfluenceDimension.LIQUIDITY.value,
    "LIQUIDITY_POOL_ESTIMATE": ConfluenceDimension.LIQUIDITY.value,
    "LIQUIDITY_SWEEP": ConfluenceDimension.LIQUIDITY.value,
    "BULLISH_FVG": ConfluenceDimension.IMBALANCE.value,
    "BEARISH_FVG": ConfluenceDimension.IMBALANCE.value,
    "BULLISH_ORDER_BLOCK": ConfluenceDimension.IMBALANCE.value,
    "BEARISH_ORDER_BLOCK": ConfluenceDimension.IMBALANCE.value,
    "BREAKER_BLOCK": ConfluenceDimension.IMBALANCE.value,
    "DISPLACEMENT": ConfluenceDimension.DISPLACEMENT.value,
    "DEALING_RANGE": ConfluenceDimension.PREMIUM_DISCOUNT.value,
    "PREMIUM": ConfluenceDimension.PREMIUM_DISCOUNT.value,
    "DISCOUNT": ConfluenceDimension.PREMIUM_DISCOUNT.value,
    "EQUILIBRIUM": ConfluenceDimension.PREMIUM_DISCOUNT.value,
    # ----------------------------------------------------------- price action
    "DOJI": ConfluenceDimension.PRICE_ACTION.value,
    "INSIDE_BAR": ConfluenceDimension.PRICE_ACTION.value,
    "OUTSIDE_BAR": ConfluenceDimension.PRICE_ACTION.value,
    "BULLISH_PIN_BAR": ConfluenceDimension.PRICE_ACTION.value,
    "BEARISH_PIN_BAR": ConfluenceDimension.PRICE_ACTION.value,
    "BULLISH_ENGULFING": ConfluenceDimension.PRICE_ACTION.value,
    "BEARISH_ENGULFING": ConfluenceDimension.PRICE_ACTION.value,
    "HAMMER": ConfluenceDimension.PRICE_ACTION.value,
    "SHOOTING_STAR": ConfluenceDimension.PRICE_ACTION.value,
    "REJECTION": ConfluenceDimension.PRICE_ACTION.value,
    "FAILED_BREAKOUT": ConfluenceDimension.PRICE_ACTION.value,
    "IMPULSION": ConfluenceDimension.PRICE_ACTION.value,
    "CONSOLIDATION": ConfluenceDimension.PRICE_ACTION.value,
    # --------------------------------------------------------------- chartist
    "SUPPORT": ConfluenceDimension.CHARTISTE.value,
    "RESISTANCE": ConfluenceDimension.CHARTISTE.value,
    "RECTANGLE": ConfluenceDimension.CHARTISTE.value,
    "CHANNEL": ConfluenceDimension.CHARTISTE.value,
    "DOUBLE_TOP": ConfluenceDimension.CHARTISTE.value,
    "DOUBLE_BOTTOM": ConfluenceDimension.CHARTISTE.value,
    "HEAD_SHOULDERS": ConfluenceDimension.CHARTISTE.value,
    "INVERSE_HEAD_SHOULDERS": ConfluenceDimension.CHARTISTE.value,
    "ASCENDING_TRIANGLE": ConfluenceDimension.CHARTISTE.value,
    "DESCENDING_TRIANGLE": ConfluenceDimension.CHARTISTE.value,
    "SYMMETRICAL_TRIANGLE": ConfluenceDimension.CHARTISTE.value,
    "TRIANGLE": ConfluenceDimension.CHARTISTE.value,
    "RISING_WEDGE": ConfluenceDimension.CHARTISTE.value,
    "FALLING_WEDGE": ConfluenceDimension.CHARTISTE.value,
    "WEDGE": ConfluenceDimension.CHARTISTE.value,
    "FLAG": ConfluenceDimension.CHARTISTE.value,
    "PENNANT": ConfluenceDimension.CHARTISTE.value,
    "BULLISH_FLAG": ConfluenceDimension.CHARTISTE.value,
    "BEARISH_FLAG": ConfluenceDimension.CHARTISTE.value,
}

#: statuses that still describe the current market (an expired object does not)
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {
        DetectionStatus.DETECTED.value,
        DetectionStatus.CONFIRMED.value,
        DetectionStatus.ACTIVE.value,
        DetectionStatus.MITIGATED.value,
        DetectionStatus.FILLED.value,
        "WATCH",
    }
)

#: order in which the real level labels of a drawing are preferred as the price
PRICE_LABEL_PREFERENCE: tuple[str, ...] = (
    "BREAK_CLOSE",
    "BROKEN_SWING",
    "LIQUIDITY_LEVEL",
    "REENTRY",
    "FAILURE_CLOSE",
    "LEVEL",
    "PATTERN_HIGH",
    "PATTERN_LOW",
    "UPPER_PRICE",
    "LOWER_PRICE",
    "ZONE_HIGH",
    "ZONE_LOW",
    "POOL_LEVEL",
    "EQUILIBRIUM",
)


def dimension_for(pattern: str, category: str) -> str:
    """Documented pattern -> dimension map, with a safe per-engine fallback."""
    known = PATTERN_DIMENSION.get(pattern.upper())
    if known:
        return known
    return FALLBACK_DIMENSION.get(category.upper(), ConfluenceDimension.STRUCTURE.value)


def reference_price(detection: PatternDetection) -> float | None:
    """A real price for the event, read from the detection's own drawing.

    Nothing is computed or interpolated: when the detection published a level, the
    level is used; otherwise the last coordinate of the detection is used; when
    neither exists the price stays ``None`` (never a guessed number).
    """
    for label in PRICE_LABEL_PREFERENCE:
        for level in detection.drawing.levels:
            if level.label == label:
                return float(level.price)
    if detection.drawing.levels:
        return float(detection.drawing.levels[0].price)
    if detection.coordinates:
        return float(detection.coordinates[-1].price)
    return None


def bar_time(detection: PatternDetection) -> int:
    """The real bar time the detection is tied to."""
    if detection.detected_at_bar_time:
        return int(detection.detected_at_bar_time)
    if detection.coordinates:
        return int(detection.coordinates[-1].time)
    return int(detection.timestamp.timestamp())


def normalise_detection(detection: PatternDetection) -> ConfluenceEvent:
    """One detection -> one common event (identity preserved)."""
    return ConfluenceEvent(
        id=detection.id,
        symbol=detection.symbol,
        timeframe=detection.timeframe.value,
        source=detection.category.value,
        type=detection.pattern,
        direction=detection.direction.value,
        dimension=dimension_for(detection.pattern, detection.category.value),
        timestamp=bar_time(detection),
        price=reference_price(detection),
        status=detection.status.value,
        confidence=detection.confidence,
        evidence=list(detection.evidence[:4]),
    )


def normalise(
    detections: list[PatternDetection],
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    keep_inactive: bool = False,
) -> list[ConfluenceEvent]:
    """Normalise a mix of detections from any engine.

    ``symbol`` / ``timeframe`` filter the input when the caller passes a global
    registry; nothing else is filtered here (an unknown pattern is kept and mapped
    to its engine dimension). Expired / invalidated objects are dropped unless the
    caller explicitly asks to keep them: they no longer describe the market.
    """
    events: list[ConfluenceEvent] = []
    for detection in detections:
        if symbol and detection.symbol.upper() != symbol.upper():
            continue
        if timeframe and detection.timeframe.value.upper() != timeframe.upper():
            continue
        if not keep_inactive and detection.status.value not in ACTIVE_STATUSES:
            continue
        events.append(normalise_detection(detection))
    events.sort(key=lambda event: (event.timestamp, event.id))
    return events
