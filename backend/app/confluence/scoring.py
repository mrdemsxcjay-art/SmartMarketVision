"""Explicable confluence score (5.4).

Rules, in full - there is nothing else behind the number:

1. the score is the sum of the points earned by the **dimensions** that carry the
   group direction. A dimension earns its weight **once**, whatever the number of
   events behind it (three fair value gaps are one reading, not three);
2. a dimension earns nothing when its events are NEUTRAL, because a neutral
   reading says nothing about a direction. Those events are still reported (as
   ``neutral`` context) and never silently dropped;
3. an opposing reading on a **major** dimension costs points instead of earning
   them; the loss is reported exactly like a gain, with the ids of the events
   responsible;
4. the total is clamped to ``[0, max_score]``; ``max_score`` is the sum of the
   weights declared in the parameters, so the score is always comparable.

What the number is NOT: a probability of success, a forecast, a target. It counts
how many independent readings agree right now.
"""

from __future__ import annotations

from app.confluence.models import ConfluenceDimension, ConfluenceEvent, ScoreComponent
from app.confluence.params import ConfluenceParams

#: human labels used in the API / dashboard (French, like the rest of the UI)
DIMENSION_LABELS: dict[str, str] = {
    ConfluenceDimension.STRUCTURE.value: "Structure",
    ConfluenceDimension.LIQUIDITY.value: "Liquidite",
    ConfluenceDimension.IMBALANCE.value: "Imbalance (FVG / OB)",
    ConfluenceDimension.DISPLACEMENT.value: "Displacement",
    ConfluenceDimension.PRICE_ACTION.value: "Price Action",
    ConfluenceDimension.CHARTISTE.value: "Chartiste",
    ConfluenceDimension.PREMIUM_DISCOUNT.value: "Premium / Discount",
    ConfluenceDimension.MULTI_TIMEFRAME.value: "Multi-timeframe",
}

#: fixed reading order of the score breakdown
DIMENSION_ORDER: tuple[str, ...] = (
    ConfluenceDimension.STRUCTURE.value,
    ConfluenceDimension.LIQUIDITY.value,
    ConfluenceDimension.IMBALANCE.value,
    ConfluenceDimension.DISPLACEMENT.value,
    ConfluenceDimension.PRICE_ACTION.value,
    ConfluenceDimension.CHARTISTE.value,
    ConfluenceDimension.PREMIUM_DISCOUNT.value,
    ConfluenceDimension.MULTI_TIMEFRAME.value,
)

WEIGHT_ATTRIBUTES: dict[str, str] = {
    ConfluenceDimension.STRUCTURE.value: "structure",
    ConfluenceDimension.LIQUIDITY.value: "liquidity",
    ConfluenceDimension.IMBALANCE.value: "imbalance",
    ConfluenceDimension.DISPLACEMENT.value: "displacement",
    ConfluenceDimension.PRICE_ACTION.value: "price_action",
    ConfluenceDimension.CHARTISTE.value: "chartiste",
    ConfluenceDimension.PREMIUM_DISCOUNT.value: "premium_discount",
    ConfluenceDimension.MULTI_TIMEFRAME.value: "multi_timeframe",
}


def weight_of(dimension: str, params: ConfluenceParams) -> float:
    attribute = WEIGHT_ATTRIBUTES.get(dimension)
    if not attribute:
        return 0.0
    return float(getattr(params.weights, attribute, 0.0))


def _describe(events: list[ConfluenceEvent]) -> tuple[str, list[str], list[str]]:
    """``(reason, ids, timeframes)`` for one dimension, from the real events."""
    by_type: dict[str, list[ConfluenceEvent]] = {}
    for event in events:
        by_type.setdefault(event.type, []).append(event)

    parts: list[str] = []
    for pattern, group in sorted(by_type.items()):
        timeframes = sorted({event.timeframe for event in group})
        suffix = f" ({', '.join(timeframes)})"
        parts.append(f"{pattern} x{len(group)}{suffix}" if len(group) > 1 else f"{pattern}{suffix}")

    ids = [event.id for event in events]
    timeframes = sorted({event.timeframe for event in events})
    return "; ".join(parts), ids, timeframes


def score_group(
    direction: str,
    aligned: list[ConfluenceEvent],
    opposing: list[ConfluenceEvent],
    params: ConfluenceParams,
    *,
    extra_components: list[ScoreComponent] | None = None,
    extra_contradictions: list[ScoreComponent] | None = None,
) -> tuple[list[ScoreComponent], list[ScoreComponent], float]:
    """Return ``(components, contradictions, total)``.

    ``aligned``   : events carrying the group direction
    ``opposing``  : events carrying the opposite direction inside the same window
    ``extra``     : components computed outside (multi-timeframe, context opposition)
    """
    components: list[ScoreComponent] = []
    by_dimension: dict[str, list[ConfluenceEvent]] = {}
    for event in aligned:
        by_dimension.setdefault(event.dimension, []).append(event)

    for dimension in DIMENSION_ORDER:
        events = by_dimension.get(dimension)
        if not events:
            continue
        points = weight_of(dimension, params)
        if points <= 0:
            continue
        reason, ids, timeframes = _describe(events)
        components.append(
            ScoreComponent(
                dimension=dimension,
                label=DIMENSION_LABELS.get(dimension, dimension),
                points=points,
                reason=reason,
                events=ids,
                timeframes=timeframes,
            )
        )

    for component in extra_components or []:
        components.append(component)

    contradictions: list[ScoreComponent] = []
    major = set(params.weights.major)
    by_opposing_dimension: dict[str, list[ConfluenceEvent]] = {}
    for event in opposing:
        if event.dimension in major:
            by_opposing_dimension.setdefault(event.dimension, []).append(event)

    penalty = float(params.states.expected_per_dimension)
    for dimension in DIMENSION_ORDER:
        events = by_opposing_dimension.get(dimension)
        if not events or penalty <= 0:
            continue
        reason, ids, timeframes = _describe(events)
        contradictions.append(
            ScoreComponent(
                dimension=dimension,
                label=DIMENSION_LABELS.get(dimension, dimension),
                points=-penalty,
                reason=f"contradiction {direction} : {reason}",
                events=ids,
                timeframes=timeframes,
            )
        )

    for component in extra_contradictions or []:
        contradictions.append(component)

    total = sum(component.points for component in components)
    total += sum(component.points for component in contradictions)
    total = max(0.0, min(round(total, 2), params.max_score()))
    return components, contradictions, total


def contradiction_points(contradictions: list[ScoreComponent]) -> float:
    """How many points the contradictions cost (a positive number)."""
    return float(-sum(component.points for component in contradictions if component.points < 0))


def explain(
    direction: str,
    components: list[ScoreComponent],
    contradictions: list[ScoreComponent],
    neutral: list[ConfluenceEvent],
) -> tuple[list[str], list[str]]:
    """The two explicit lists of 5.7: why the context holds, what opposes it."""
    why: list[str] = []
    verb = "haussier" if direction == "BULLISH" else ("baissier" if direction == "BEARISH" else "neutre")
    for component in components:
        timeframes = ", ".join(component.timeframes) if component.timeframes else "-"
        why.append(
            f"{component.label} {verb} ({timeframes}) : {component.reason} [+{component.points:g}]"
        )
    if not why:
        why.append("aucun element directionnel observe")

    against: list[str] = []
    for component in contradictions:
        timeframes = ", ".join(component.timeframes) if component.timeframes else "-"
        against.append(f"{component.label} oppose ({timeframes}) : {component.reason} [{component.points:g}]")
    if not against:
        against.append("aucun element oppose majeur dans la fenetre")

    if neutral:
        types = sorted({event.type for event in neutral})
        against.append(
            "lecture(s) neutre(s), informative(s) : " + ", ".join(types)
        )
    return why, against
