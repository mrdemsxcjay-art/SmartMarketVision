"""Order blocks (§11) and breaker blocks (§12).

Order block - one deterministic definition, always the same:
the LAST OPPOSITE candle before a displacement that breaks structure. For a
bullish block: take the last bearish candle before a bullish BOS / CHOCH / MSS,
require a displacement bar in the same move, and keep the origin candle's range
(or its body, if ``order_block.zone_from_body``). The trigger event is stored
with the block, so the dashboard can always say *why* the zone exists.

Breaker block - **never detected on its own**. It is the promotion of an
existing order block along an explicit cycle:

    ORDER_BLOCK -> INVALIDATION (a close through the zone)
                -> STRUCTURAL_BREAK (BOS/CHOCH the other way)
                -> BREAKER

A block invalidated without that structural break stays invalidated. There is no
function anywhere that invents a breaker from raw candles.
"""

from __future__ import annotations

from app.price_action.candles import ge, gt, le, lt
from app.smc_ict.measures import displacement_of, is_displacement
from app.smc_ict.models import ScanContext, SmcCandidate


def _trigger_candidates(structure: list[SmcCandidate]) -> list[SmcCandidate]:
    return [c for c in structure if c.pattern in ("BOS", "CHOCH", "MSS")]


def _origin_index(ctx: ScanContext, *, break_index: int, displacement_index: int, direction: str) -> int | None:
    """Last opposite candle before (and including) the displacement bar."""
    params = ctx.params.order_block
    start = max(0, displacement_index - params.max_bars_to_break)
    for index in range(displacement_index, start - 1, -1):
        bar = ctx.metrics[index]
        if direction == "BULLISH" and lt(bar.close, bar.open):
            return index
        if direction == "BEARISH" and gt(bar.close, bar.open):
            return index
    return None


def block_state(
    ctx: ScanContext,
    *,
    direction: str,
    low: float,
    high: float,
    from_index: int,
    newest: int,
) -> dict[str, object]:
    """Where the block stands now: untouched, mitigated, invalidated."""
    buffer = ctx.params.breaker.invalidation_close_buffer_pips * ctx.pip_size
    touched_index = None
    invalidated_index = None
    for index in range(from_index + 1, newest + 1):
        bar = ctx.metrics[index]
        if touched_index is None and not (lt(bar.high, low) or gt(bar.low, high)):
            touched_index = index
        if direction == "BULLISH" and lt(bar.close, low - buffer):
            invalidated_index = index
            break
        if direction == "BEARISH" and gt(bar.close, high + buffer):
            invalidated_index = index
            break

    if invalidated_index is not None:
        state = "INVALIDATED"
    elif touched_index is not None:
        state = "MITIGATED"
    else:
        state = "ACTIVE"
    return {
        "state": state,
        "touched": touched_index is not None,
        "touch_index": touched_index,
        "invalidated": invalidated_index is not None,
        "invalidation_index": invalidated_index,
        "age_bars": newest - from_index,
    }


def detect_order_blocks(ctx: ScanContext, structure: list[SmcCandidate]) -> list[SmcCandidate]:
    """§11 - order blocks anchored on a real structural break."""
    params = ctx.params
    block_params = params.order_block
    weights = params.weights
    if len(ctx.metrics) < params.global_.min_bars_required:
        return []

    newest = len(ctx.metrics) - 1
    out: list[SmcCandidate] = []
    seen_origins: set[tuple[str, int]] = set()

    for trigger in _trigger_candidates(structure):
        direction = trigger.direction
        break_index = trigger.index
        if newest - break_index > block_params.max_block_age_bars:
            continue

        displacement_index = None
        origin_index = None
        for offset in range(0, block_params.max_bars_to_break + 1):
            index = break_index - offset
            if index < 0:
                break
            passed, measures = is_displacement(ctx, index)
            if not passed:
                continue
            origin = _origin_index(
                ctx, break_index=break_index, displacement_index=index, direction=direction
            )
            if origin is None:
                continue
            if index - origin > block_params.max_bars_to_break:
                continue
            displacement_index, origin_index, origin_measures = index, origin, measures
            break
        if displacement_index is None or origin_index is None:
            continue

        key = (direction, origin_index)
        if key in seen_origins:
            continue
        seen_origins.add(key)

        origin = ctx.metrics[origin_index]
        if block_params.zone_from_body:
            low, high = min(origin.open, origin.close), max(origin.open, origin.close)
            zone_source = "corps de la bougie d'origine"
        else:
            low, high = origin.low, origin.high
            zone_source = "range complet de la bougie d'origine"

        state = block_state(
            ctx, direction=direction, low=low, high=high, from_index=displacement_index, newest=newest
        )
        if state["age_bars"] > block_params.max_block_age_bars:
            continue

        pattern = "BULLISH_ORDER_BLOCK" if direction == "BULLISH" else "BEARISH_ORDER_BLOCK"
        criteria = [
            (
                "Bougie d'origine opposée identifiée",
                True,
                weights.structure,
                f"#{origin_index} {'baissière' if direction == 'BULLISH' else 'haussière'} "
                f"(O {origin.open:.5f} C {origin.close:.5f}), {zone_source}",
            ),
            (
                "Déplacement mesuré avant la cassure",
                True,
                weights.displacement,
                f"bougie #{displacement_index} : range {origin_measures['range_pips']} pip "
                f"({origin_measures['range_atr']} ATR), corps/range {origin_measures['body_ratio']}, "
                f"progression {origin_measures['progression_pips']} pip",
            ),
            (
                "Cassure structurelle déclenchante",
                True,
                weights.structure,
                f"{trigger.pattern} {direction} en bougie {break_index} "
                f"({break_index - displacement_index} bougie(s) après le déplacement)",
            ),
            (
                "Distance origine -> cassure dans la limite",
                break_index - origin_index <= block_params.max_bars_to_break,
                weights.context,
                f"{break_index - origin_index} bougie(s) (maximum {block_params.max_bars_to_break})",
            ),
            (
                f"État du bloc : {state['state']}",
                True,
                weights.context,
                f"touché : {state['touched']}, invalidé : {state['invalidated']}, "
                f"{state['age_bars']} bougie(s)",
            ),
        ]
        out.append(
            SmcCandidate(
                pattern=pattern,
                direction=direction,
                index=displacement_index,
                time=ctx.metrics[displacement_index].time,
                criteria=criteria,
                evidence=[
                    f"Bloc {direction} : bougie d'origine #{origin_index} "
                    f"[{low:.5f} - {high:.5f}]",
                    f"Déplacement #{displacement_index} puis {trigger.pattern} en bougie {break_index}",
                    f"Définition unique : dernière bougie opposée avant un déplacement qui casse la structure",
                    "Aucune notion de zone 'supply/demand' vague : chaque bloc porte son événement déclencheur",
                ],
                measurements={
                    "origin_index": origin_index,
                    "displacement_index": displacement_index,
                    "break_index": break_index,
                    "trigger_pattern": trigger.pattern,
                    "displacement": origin_measures,
                    "zone_source": zone_source,
                    **state,
                },
                levels={
                    "ZONE_HIGH": round(high, 8),
                    "ZONE_LOW": round(low, 8),
                    "ORIGIN_OPEN": round(origin.open, 8),
                    "ORIGIN_CLOSE": round(origin.close, 8),
                },
                zones=[
                    {
                        "time_start": origin.time,
                        "time_end": ctx.metrics[newest].time,
                        "price_top": round(high, 8),
                        "price_bottom": round(low, 8),
                        "label": pattern,
                        "kind": "ORDER_BLOCK",
                    }
                ],
                markers=[
                    {
                        "time": origin.time,
                        "price": (high + low) / 2,
                        "position": "aboveBar" if direction == "BEARISH" else "belowBar",
                        "shape": "square",
                        "label": "OB",
                        "kind": "HIGH" if direction == "BEARISH" else "LOW",
                    }
                ],
                coordinates=[(origin_index, high, "OB_TOP", "order block top"), (origin_index, low, "OB_BOTTOM", "order block bottom")],
                extra={
                    "origin_candle": {
                        "index": origin_index,
                        "time": origin.time,
                        "open": origin.open,
                        "high": origin.high,
                        "low": origin.low,
                        "close": origin.close,
                    },
                    "zone_high": round(high, 8),
                    "zone_low": round(low, 8),
                    "direction": direction,
                    "trigger_event": {"pattern": trigger.pattern, "index": break_index, "direction": trigger.direction},
                    "displacement_measure": origin_measures,
                    "state": state["state"],
                    "origin_index": origin_index,
                },
                source_from_index=origin_index,
                family="BLOCKS",
            )
        )
    out.sort(key=lambda c: c.index, reverse=True)
    return out[: block_params.max_tracked]


def detect_breakers(
    ctx: ScanContext,
    order_blocks: list[SmcCandidate],
    structure: list[SmcCandidate],
) -> list[SmcCandidate]:
    """§12 - breakers derived from invalidated order blocks, never detected alone."""
    params = ctx.params
    breaker = params.breaker
    weights = params.weights
    newest = len(ctx.metrics) - 1
    out: list[SmcCandidate] = []

    for block in order_blocks:
        if not block.measurements.get("invalidated"):
            continue
        invalid_index = block.measurements.get("invalidation_index")
        if invalid_index is None:
            continue
        invalid_index = int(invalid_index)
        if newest - invalid_index > breaker.max_bars_to_promote:
            continue

        opposite = "BEARISH" if block.direction == "BULLISH" else "BULLISH"
        break_after = [
            c
            for c in _trigger_candidates(structure)
            if c.direction == opposite
            and c.index >= invalid_index
            and c.index - invalid_index <= breaker.max_bars_to_promote
        ]
        if breaker.require_structural_break and not break_after:
            continue  # invalidated, but never promoted: no structural break
        promotion = min(break_after, key=lambda c: c.index) if break_after else None

        low = float(block.levels["ZONE_LOW"])
        high = float(block.levels["ZONE_HIGH"])
        criteria = [
            (
                "Étape 1 - bloc d'origine qualifié",
                True,
                weights.structure,
                f"{block.pattern} sur la bougie d'origine #{block.extra['origin_index']}",
            ),
            (
                "Étape 2 - invalidation par clôture à travers la zone",
                True,
                weights.structure,
                f"clôture au-delà de la zone en bougie {invalid_index} "
                f"(tampon {breaker.invalidation_close_buffer_pips} pip)",
            ),
            (
                "Étape 3 - cassure structurelle opposée",
                bool(break_after),
                weights.structure,
                f"{promotion.pattern} {opposite} en bougie {promotion.index}"
                if promotion
                else "aucune cassure structurelle opposée : promotion refusée",
            ),
            (
                "Cycle explicite ORDER_BLOCK -> INVALIDATION -> STRUCTURAL_BREAK -> BREAKER",
                True,
                weights.context,
                "le breaker n'est jamais détecté seul, il est dérivé de ce cycle",
            ),
        ]
        out.append(
            SmcCandidate(
                pattern="BREAKER_BLOCK",
                direction=opposite,
                index=promotion.index if promotion else invalid_index,
                time=ctx.metrics[promotion.index if promotion else invalid_index].time,
                criteria=criteria,
                evidence=[
                    f"Breaker {opposite} dérivé de {block.pattern} (zone {low:.5f} - {high:.5f})",
                    f"Invalidation en bougie {invalid_index}, cassure structurelle "
                    f"{promotion.pattern if promotion else '-'} en bougie {promotion.index if promotion else '-'}",
                    "Le breaker réutilise la zone du bloc invalidé : aucune zone n'est inventée",
                ],
                measurements={
                    "origin_block_pattern": block.pattern,
                    "origin_index": block.extra["origin_index"],
                    "invalidation_index": invalid_index,
                    "promotion_pattern": promotion.pattern if promotion else None,
                    "promotion_index": promotion.index if promotion else None,
                    "bars_invalidation_to_break": (promotion.index - invalid_index) if promotion else None,
                },
                levels={
                    "ZONE_HIGH": round(high, 8),
                    "ZONE_LOW": round(low, 8),
                },
                zones=[
                    {
                        "time_start": ctx.metrics[int(block.extra["origin_index"])].time,
                        "time_end": ctx.metrics[newest].time,
                        "price_top": round(high, 8),
                        "price_bottom": round(low, 8),
                        "label": "BREAKER_BLOCK",
                        "kind": "BREAKER",
                    }
                ],
                markers=[
                    {
                        "time": ctx.metrics[promotion.index if promotion else invalid_index].time,
                        "price": (high + low) / 2,
                        "position": "aboveBar" if opposite == "BEARISH" else "belowBar",
                        "shape": "square",
                        "label": "BREAKER",
                        "kind": "HIGH" if opposite == "BEARISH" else "LOW",
                    }
                ],
                coordinates=[(int(block.extra["origin_index"]), high, "BREAKER_TOP", "breaker top")],
                extra={
                    "origin_block": block.pattern,
                    "origin_index": block.extra["origin_index"],
                    "zone_high": round(high, 8),
                    "zone_low": round(low, 8),
                    "direction": opposite,
                    "cycle": ["ORDER_BLOCK", "INVALIDATION", "STRUCTURAL_BREAK", "BREAKER"],
                },
                source_from_index=int(block.extra["origin_index"]),
                family="BLOCKS",
            )
        )
    out.sort(key=lambda c: c.index, reverse=True)
    return out


def zone_holding(ctx: ScanContext, candidate: SmcCandidate) -> bool:
    """True while price still respects a block/zone (used by the confluence layer)."""
    bar = ctx.metrics[-1]
    low = float(candidate.levels.get("ZONE_LOW", 0.0))
    high = float(candidate.levels.get("ZONE_HIGH", 0.0))
    return ge(bar.close, low) and le(bar.close, high)
