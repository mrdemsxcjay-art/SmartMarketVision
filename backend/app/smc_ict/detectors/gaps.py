"""Fair value gaps (§9) and their mitigation lifecycle (§10).

A fair value gap is a band that price crossed so fast that it never traded there:
``low[i+2] > high[i]`` for a bullish gap (the mirror for a bearish one). The
engine never calls it "unfilled volume" - the provider gives no volume, so the
only thing that is claimed is that **price did not trade that band**, because it
is measured on the candles themselves.

Lifecycle (never a guess, always recomputed from the bars):

* ``CREATED`` - just formed, and not touched yet;
* ``ACTIVE`` - it survived ``activation_bars`` bars; a marginal touch that stays
  below ``partial_share`` of the band keeps it ACTIVE, and is reported by
  ``touched`` so nothing is hidden;
* ``PARTIALLY_FILLED`` - price entered the band and covered at least
  ``partial_share`` of it without traversing it entirely;
* ``FILLED`` - the band was traversed entirely (``fill_rule = full_traverse``) or
  closed beyond (``close_beyond``).

Coverage is the measured union of the bands the later candles actually traded:
that is a number, not an opinion.
"""

from __future__ import annotations

from app.price_action.candles import ge, gt, le, lt
from app.smc_ict.models import ScanContext, SmcCandidate


def _band_overlap(bar_low: float, bar_high: float, low: float, high: float) -> float:
    top = min(bar_high, high)
    bottom = max(bar_low, low)
    return max(0.0, top - bottom)


def coverage_of(ctx: ScanContext, *, low: float, high: float, start_index: int) -> dict[str, object]:
    """Union of the traded parts of ``[low, high]`` after ``start_index``."""
    band = high - low
    intervals: list[tuple[float, float]] = []
    for bar in ctx.metrics[start_index + 1 :]:
        size = _band_overlap(bar.low, bar.high, low, high)
        if size > 0:
            intervals.append((max(bar.low, low), min(bar.high, high)))
    merged: list[list[float]] = []
    for bottom, top in sorted(intervals):
        if merged and bottom <= merged[-1][1] + 1e-12:
            merged[-1][1] = max(merged[-1][1], top)
        else:
            merged.append([bottom, top])
    covered = sum(top - bottom for bottom, top in merged)
    share = covered / band if band > 0 else 1.0
    touched = bool(merged)
    first_touch = None
    for offset, bar in enumerate(ctx.metrics[start_index + 1 :], start=start_index + 1):
        if _band_overlap(bar.low, bar.high, low, high) > 0:
            first_touch = offset
            break
    return {
        "coverage_share": round(min(1.0, share), 6),
        "covered_price": round(covered, 8),
        "band_size": round(band, 8),
        "touched": touched,
        "first_touch_index": first_touch,
    }


def mitigation_state(
    ctx: ScanContext,
    *,
    direction: str,
    low: float,
    high: float,
    created_index: int,
    newest: int,
) -> dict[str, object]:
    """State of a gap as of the newest bar, with the numbers behind it."""
    params = ctx.params.mitigation
    age = newest - created_index
    coverage = coverage_of(ctx, low=low, high=high, start_index=created_index)

    traversed = False
    close_beyond = False
    for index in range(created_index + 1, newest + 1):
        bar = ctx.metrics[index]
        # the band is traversed when a single candle's range covers ALL of it
        # (bar low at or below the band, bar high at or above it)
        if le(bar.low, low) and ge(bar.high, high):
            traversed = True
        if direction == "BULLISH" and lt(bar.close, low):
            close_beyond = True
        if direction == "BEARISH" and gt(bar.close, high):
            close_beyond = True

    if params.fill_rule == "close_beyond":
        filled = close_beyond
    else:
        filled = traversed or float(coverage["coverage_share"]) >= 1.0

    if filled:
        state = "FILLED"
    elif float(coverage["coverage_share"]) >= params.partial_share:
        state = "PARTIALLY_FILLED"
    elif age < params.activation_bars:
        state = "CREATED"
    else:
        state = "ACTIVE"

    return {
        "state": state,
        "age_bars": age,
        "coverage_share": coverage["coverage_share"],
        "covered_price": coverage["covered_price"],
        "band_size": coverage["band_size"],
        "touched": coverage["touched"],
        "first_touch_index": coverage["first_touch_index"],
        "traversed": traversed,
        "close_beyond": close_beyond,
        "expired": age > params.expiry_bars,
    }


def detect_fvgs(ctx: ScanContext) -> list[SmcCandidate]:
    """§9 + §10 - FVG candidates with their current mitigation state."""
    params = ctx.params
    fvg = params.fvg
    if len(ctx.metrics) < params.global_.min_bars_required:
        return []

    newest = len(ctx.metrics) - 1
    floor = ctx.min_size(fvg.min_size_pips, fvg.min_size_atr)
    found: list[SmcCandidate] = []

    for index in range(max(2, newest - fvg.max_gap_age_bars), newest - 1):
        first = ctx.metrics[index]
        third = ctx.metrics[index + 2]
        bullish = gt(third.low, first.high)
        bearish = lt(third.high, first.low)
        if not bullish and not bearish:
            continue
        if bullish:
            low, high, direction, pattern = first.high, third.low, "BULLISH", "BULLISH_FVG"
        else:
            low, high, direction, pattern = third.high, first.low, "BEARISH", "BEARISH_FVG"
        size = high - low
        if not ge(size, floor):
            continue

        state = mitigation_state(
            ctx, direction=direction, low=low, high=high, created_index=index + 2, newest=newest
        )
        if state["expired"]:
            continue

        middle = ctx.metrics[index + 1]
        criteria = [
            (
                "Écart de trois bougies mesuré",
                True,
                params.weights.geometry,
                f"bougie 1 high {first.high:.5f} / bougie 3 low {third.low:.5f}"
                if bullish
                else f"bougie 3 high {third.high:.5f} / bougie 1 low {first.low:.5f}",
            ),
            (
                "Taille minimale",
                ge(size, floor),
                params.weights.geometry,
                f"taille {ctx.pips(size):.2f} pip (seuil {ctx.pips(floor):.2f} pip = "
                f"max({fvg.min_size_pips} pips, {fvg.min_size_atr} ATR))",
            ),
            (
                "Bande jamais tradée",
                True,
                params.weights.structure,
                "le prix n'a pas tradé cette bande entre la bougie 1 et la bougie 3",
            ),
            (
                f"État de mitigation : {state['state']}",
                True,
                params.weights.context,
                f"couverture {float(state['coverage_share']) * 100:.1f}% de la bande, "
                f"{state['age_bars']} bougie(s) depuis la formation",
            ),
        ]
        evidence = [
            f"FVG {direction} formé en bougie {index + 2} : bande {low:.5f} - {high:.5f} "
            f"({ctx.pips(size):.2f} pip)",
            f"Bougies : 1=#{index} (H {first.high:.5f}), 2=#{index + 1} (range {ctx.pips(middle.range):.2f} pip), "
            f"3=#{index + 2} (L {third.low:.5f})",
            f"Mitigation : {state['state']} - couverture {float(state['coverage_share']) * 100:.1f}%, "
            f"traversée complète : {state['traversed']}",
            "Aucun volume n'est utilisé : le moteur décrit une bande non tradée, pas un carnet d'ordres",
        ]
        found.append(
            SmcCandidate(
                pattern=pattern,
                direction=direction,
                index=index + 2,
                time=third.time,
                criteria=criteria,
                evidence=evidence,
                measurements={
                    "size_pips": round(ctx.pips(size), 2),
                    "size_atr": round(ctx.atr_multiple(size), 4),
                    "candle_1_index": index,
                    "candle_2_index": index + 1,
                    "candle_3_index": index + 2,
                    **state,
                },
                levels={
                    "UPPER_PRICE": round(high, 8),
                    "LOWER_PRICE": round(low, 8),
                    "SIZE": round(size, 8),
                },
                zones=[
                    {
                        "time_start": ctx.metrics[index].time,
                        "time_end": ctx.metrics[newest].time,
                        "price_top": round(high, 8),
                        "price_bottom": round(low, 8),
                        "label": pattern,
                        "kind": "FVG",
                    }
                ],
                markers=[
                    {
                        "time": third.time,
                        "price": (high + low) / 2,
                        "position": "aboveBar" if direction == "BEARISH" else "belowBar",
                        "shape": "square",
                        "label": "FVG",
                        "kind": "HIGH" if direction == "BEARISH" else "LOW",
                    }
                ],
                coordinates=[
                    (index, first.high if bullish else first.low, "CANDLE_1", "fvg candle 1"),
                    (index + 1, middle.close, "CANDLE_2", "fvg candle 2"),
                    (index + 2, third.low if bullish else third.high, "CANDLE_3", "fvg candle 3"),
                ],
                extra={
                    "direction": direction,
                    "candle_1": {
                        "index": index,
                        "time": first.time,
                        "open": first.open,
                        "high": first.high,
                        "low": first.low,
                        "close": first.close,
                    },
                    "candle_2": {
                        "index": index + 1,
                        "time": middle.time,
                        "open": middle.open,
                        "high": middle.high,
                        "low": middle.low,
                        "close": middle.close,
                    },
                    "candle_3": {
                        "index": index + 2,
                        "time": third.time,
                        "open": third.open,
                        "high": third.high,
                        "low": third.low,
                        "close": third.close,
                    },
                    "state": state["state"],
                    "mitigation": state,
                },
                source_from_index=index,
                family="GAPS",
            )
        )

    found.sort(key=lambda c: c.index, reverse=True)
    return found[: fvg.max_tracked]
