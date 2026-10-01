"""Structural detectors: BOS, CHOCH, MSS.

Definitions used (single, documented, never combined with another)
------------------------------------------------------------------
**BOS (Break Of Structure)** - the prevailing structure continues. A candle
*closes* beyond the most recent confirmed swing in the direction of that
structure. A wick alone is NOT a BOS unless ``bos.allow_wick_break`` is raised,
and even then the wick must clear the level by ``wick_buffer_pips``.

**CHOCH (Change Of Character)** - the prevailing structure is broken the *other*
way: a bearish structure whose last swing high is closed above (bearish ->
bullish), or the mirror image. The swing that was broken is returned explicitly,
as is the confirmation candle.

**MSS (Market Structure Shift)** - a CHOCH **immediately followed by a
displacement** in the new direction (close beyond the CHOCH level by
``mss.min_displacement_atr`` ATR, body ratio >= ``mss.min_body_ratio``, within
``mss.max_bars_after_choch`` bars). A CHOCH without displacement stays a CHOCH
and is never relabelled. MSS is therefore a strict superset test applied to a
confirmed CHOCH - the two definitions never contradict each other.

When the structure before the break is UNDEFINED / RANGE, the engine reports a
BOS and says so explicitly in the evidence: it never invents a change of
character that has no character to change.
"""

from __future__ import annotations

from app.price_action.candles import ge, gt
from app.smc_ict.context import dominant_structure
from app.smc_ict.measures import is_displacement
from app.smc_ict.models import ScanContext, SmcCandidate, SmcSwing
from app.smc_ict.params import SmcIctParams


def _break_threshold(ctx: ScanContext, pattern_params) -> float:
    return ctx.min_size(pattern_params.min_break_pips, pattern_params.min_break_atr)


def _scan_indices(ctx: ScanContext, scan_bars: int | None = None) -> list[int]:
    """Bar indices to inspect, oldest first (so a level is broken only once).

    ``scan_bars=None`` uses the live window (``globals.scan_bars``): only the
    newest bars can produce a *new* event. Long-lived objects (order blocks,
    breakers) re-read a wider history through ``globals.structure_bars``.
    """
    newest = len(ctx.metrics) - 1
    width = scan_bars or ctx.params.global_.scan_bars
    oldest = max(0, newest - width + 1)
    return list(range(oldest, newest + 1))


def detect_structure(ctx: ScanContext, scan_bars: int | None = None) -> list[SmcCandidate]:
    """BOS, CHOCH and MSS candidates for the scanned window.

    ``scan_bars`` overrides how far back the scan goes (see :func:`_scan_indices`).
    """
    params: SmcIctParams = ctx.params
    if len(ctx.metrics) < params.global_.min_bars_required or not ctx.swings:
        return []

    candidates: list[SmcCandidate] = []
    broken: set[int] = set()          # swing index already broken in this run
    used: set[int] = set()            # swing index already reported (one event per level)
    chochs: list[SmcCandidate] = []

    # The prevailing structure is read from the swings confirmed AT THAT MOMENT,
    # never from the whole series: reading it once for all bars would let a later
    # swing decide what the structure was before the break (look-ahead).
    structure_cache: dict[int, tuple[str, str]] = {}

    def structure_at(index: int) -> tuple[str, str]:
        eligible = [s for s in ctx.swings if s.confirmed_at_index <= index]
        key = len(eligible)
        if key not in structure_cache:
            structure_cache[key] = dominant_structure(eligible, params.choch.min_swings_for_trend)
        return structure_cache[key]

    for index in _scan_indices(ctx, scan_bars):
        bar = ctx.metrics[index]
        direction, reason = structure_at(index)
        # Only the MOST RECENT confirmed swing of each kind is breakable, and a
        # level breaks once. Without that rule a single impulse would "break" the
        # whole ladder of older swings and emit one BOS per bar - exactly the
        # over-detection the brief forbids.
        # The most recent confirmed swing ONLY. Skipping back to older levels would
        # emit one BOS per bar of the same impulse, which is not what a break of
        # structure is: one impulse, one level, one event.
        available_highs = [s for s in ctx.swings if s.is_high and s.confirmed_at_index <= index]
        available_lows = [s for s in ctx.swings if not s.is_high and s.confirmed_at_index <= index]

        if available_highs:
            swing = available_highs[-1]
            if swing.index not in used:
                candidate = _break_candidate(ctx, bar_index=index, swing=swing, direction="BULLISH", structure=direction, reason=reason)
                if candidate:
                    broken.add(swing.index)
                    used.add(swing.index)
                    candidates.append(candidate)
                    if candidate.pattern == "CHOCH":
                        chochs.append(candidate)

        if available_lows:
            swing = available_lows[-1]
            if swing.index not in used:
                candidate = _break_candidate(ctx, bar_index=index, swing=swing, direction="BEARISH", structure=direction, reason=reason)
                if candidate:
                    broken.add(swing.index)
                    used.add(swing.index)
                    candidates.append(candidate)
                    if candidate.pattern == "CHOCH":
                        chochs.append(candidate)

    candidates.extend(_mss_from_choch(ctx, chochs))
    return candidates


def _break_candidate(
    ctx: ScanContext,
    bar_index: int,
    swing: SmcSwing,
    direction: str,
    structure: str,
    reason: str,
) -> SmcCandidate | None:
    """One break test: is this candle closing beyond that swing?"""
    params = ctx.params
    bar = ctx.metrics[bar_index]
    bullish = direction == "BULLISH"
    level = swing.price
    threshold = _break_threshold(ctx, params.bos)

    # ---- distance actually cleared
    if bullish:
        close_excess = bar.close - level
        wick_excess = bar.high - level
    else:
        close_excess = level - bar.close
        wick_excess = level - bar.low

    if bar_index - swing.index > params.bos.max_bars_since_swing:
        return None

    # ---- the break is close-based; a wick alone only counts when the parameter
    # explicitly allows it, and it must then clear the level by the buffer
    close_ok = gt(close_excess, threshold)
    wick_buffer = params.bos.wick_buffer_pips * ctx.pip_size
    wick_ok = gt(wick_excess, threshold + wick_buffer)
    body_beyond = (
        gt(min(bar.open, bar.close), level) if bullish else gt(level, max(bar.open, bar.close))
    )
    if close_ok:
        break_mode = "CLOSE"
    elif params.bos.allow_wick_break and wick_ok:
        break_mode = "WICK"
    else:
        return None

    # ---- BOS or CHOCH?
    opposite = "BEARISH" if bullish else "BULLISH"
    if structure == opposite:
        pattern = "CHOCH"
        family = "STRUCTURE"
    else:
        pattern = "BOS"
        family = "STRUCTURE"

    bars_since = bar_index - swing.index
    criteria = [
        (
            "Swing confirmé disponible",
            True,
            params.weights.structure,
            f"{swing.type_label} #{swing.index} à {swing.price:.5f} (force {swing.strength})",
        ),
        (
            "Clôture au-delà du niveau",
            close_ok,
            params.weights.structure,
            f"clôture {bar.close:.5f} vs niveau {level:.5f} "
            f"({ctx.pips(close_excess):.2f} pip au-delà, seuil {ctx.pips(threshold):.2f} pip)",
        ),
        (
            "Excursion suffisante",
            ge(abs(close_excess), threshold),
            params.weights.geometry,
            f"seuil = max({params.bos.min_break_pips} pips, {params.bos.min_break_atr} ATR) = {threshold:.5f}",
        ),
        (
            "Swing encore valide (non périmé)",
            bars_since <= params.bos.max_bars_since_swing,
            params.weights.context,
            f"{bars_since} bougie(s) depuis le swing (limite {params.bos.max_bars_since_swing})",
        ),
        (
            "Cassure portée par le corps (pas une mèche)",
            body_beyond,
            params.weights.geometry,
            (
                f"corps entièrement au-delà du niveau : {body_beyond} ; mesure retenue : {break_mode}"
                + (
                    f" (mèche {ctx.pips(wick_excess):.2f} pip, autorisée par allow_wick_break=true)"
                    if break_mode == "WICK"
                    else " ; mèche seule refusée (allow_wick_break=false)"
                )
            ),
        ),
    ]

    measurements = {
        "swing_index": swing.index,
        "swing_price": round(level, 8),
        "swing_strength": swing.strength,
        "bars_since_swing": bars_since,
        "close_excess_pips": round(ctx.pips(close_excess), 2),
        "close_excess_atr": round(ctx.atr_multiple(close_excess), 4),
        "wick_excess_pips": round(ctx.pips(max(0.0, wick_excess)), 2),
        "threshold_pips": round(ctx.pips(threshold), 2),
        "threshold": round(threshold, 8),
        "structure_before": structure,
        "structure_after": direction,
        "body_beyond_level": body_beyond,
        "break_mode": break_mode,
        "close_break": close_ok,
        "atr": round(ctx.atr, 8),
    }

    evidence = [
        f"{swing.type_label} #{swing.index} à {swing.price:.5f} (force {swing.strength}, confirmé en bougie {swing.confirmed_at_index})",
        f"Bougie {bar_index} : O {bar.open:.5f} H {bar.high:.5f} L {bar.low:.5f} C {bar.close:.5f}",
        f"Clôture {bar.close:.5f} vs niveau {level:.5f} ({ctx.pips(close_excess):.2f} pip), cassure retenue : {break_mode}",
        f"Structure préalable : {structure} — {reason}",
    ]
    if pattern == "BOS":
        evidence.append(
            "Cassure dans le sens de la structure : BOS"
            if structure in ("BULLISH", "BEARISH")
            else "Structure préalable indéterminée : cassure classée BOS (aucun changement de caractère invoqué)"
        )
    else:
        evidence.append(f"Changement de caractère : {opposite} -> {direction}")

    marker_position = "aboveBar" if bullish else "belowBar"
    return SmcCandidate(
        pattern=pattern,
        direction=direction,
        index=bar_index,
        time=bar.time,
        criteria=criteria,
        evidence=evidence,
        measurements=measurements,
        levels={
            "BROKEN_SWING": round(level, 8),
            "BREAK_CLOSE": round(bar.close, 8),
        },
        zones=[
            {
                "time_start": swing.time,
                "time_end": bar.time,
                "price_top": round(max(level, bar.close), 8),
                "price_bottom": round(min(level, bar.close), 8),
                "label": pattern,
                "kind": "STRUCTURE_BREAK",
            }
        ],
        markers=[
            {
                "time": bar.time,
                "price": bar.close,
                "position": marker_position,
                "shape": "arrowUp" if bullish else "arrowDown",
                "label": pattern,
                "kind": "HIGH" if bullish else "LOW",
            }
        ],
        coordinates=[
            (bar_index, bar.close, "BREAK", f"{pattern} close"),
        ],
        extra={"structure_before": structure, "structure_after": direction, "broken_swing": swing.as_dict()},
        source_from_index=swing.index,
        family=family,
    )


def _mss_from_choch(ctx: ScanContext, chochs: list[SmcCandidate]) -> list[SmcCandidate]:
    """Promote a confirmed CHOCH to MSS when a displacement follows it."""
    params = ctx.params
    out: list[SmcCandidate] = []
    for choch in chochs:
        direction = choch.direction
        deadline = min(len(ctx.metrics) - 1, choch.index + params.mss.max_bars_after_choch)
        for index in range(choch.index, deadline + 1):
            passed, measures = is_displacement(ctx, index)
            if not passed:
                continue
            bar = ctx.metrics[index]
            level = float(choch.levels["BROKEN_SWING"])
            # the displacement must actually extend beyond the CHOCH level
            extension = (bar.close - level) if direction == "BULLISH" else (level - bar.close)
            if not gt(extension, params.mss.min_displacement_atr * ctx.atr):
                continue

            criteria = [
                (
                    "CHOCH confirmé",
                    True,
                    params.weights.structure,
                    f"CHOCH {direction} en bougie {choch.index} sur le niveau {level:.5f}",
                ),
                (
                    "Déplacement mesuré",
                    True,
                    params.weights.displacement,
                    f"range {measures['range_pips']} pips / {measures['range_atr']} ATR "
                    f"(seuil {params.displacement.min_range_pips} pips / {params.displacement.min_range_atr} ATR)",
                ),
                (
                    "Corps dominant",
                    ge(float(measures["body_ratio"]), params.displacement.min_body_ratio),
                    params.weights.displacement,
                    f"corps/range {measures['body_ratio']} (seuil {params.displacement.min_body_ratio})",
                ),
                (
                    "Progression au-delà du niveau CHOCH",
                    gt(extension, params.mss.min_displacement_atr * ctx.atr),
                    params.weights.structure,
                    f"{ctx.atr_multiple(extension):.2f} ATR au-delà (seuil {params.mss.min_displacement_atr})",
                ),
                (
                    "Délai respecté",
                    index - choch.index <= params.mss.max_bars_after_choch,
                    params.weights.context,
                    f"{index - choch.index} bougie(s) après le CHOCH (limite {params.mss.max_bars_after_choch})",
                ),
            ]
            out.append(
                SmcCandidate(
                    pattern="MSS",
                    direction=direction,
                    index=index,
                    time=bar.time,
                    criteria=criteria,
                    evidence=[
                        f"CHOCH {direction} en bougie {choch.index} (niveau {level:.5f})",
                        f"Déplacement en bougie {index} : range {measures['range_pips']} pips "
                        f"({measures['range_atr']} ATR), corps/range {measures['body_ratio']}",
                        f"Progression de {ctx.atr_multiple(extension):.2f} ATR au-delà du niveau",
                        "MSS = CHOCH + déplacement (définition unique, jamais combinée à une autre)",
                    ],
                    measurements={
                        "from_choch_index": choch.index,
                        "choch_index": choch.index,
                        "choch_level": round(level, 8),
                        "bars_after_choch": index - choch.index,
                        "extension_atr": round(ctx.atr_multiple(extension), 4),
                        **{k: v for k, v in measures.items()},
                    },
                    levels={
                        # same contract as BOS / CHOCH: the level that was broken and
                        # the close that broke it, so the API exposes one shape only
                        "BROKEN_SWING": round(level, 8),
                        "BREAK_CLOSE": round(bar.close, 8),
                        "CHOCH_LEVEL": round(level, 8),
                        "SHIFT_CLOSE": round(bar.close, 8),
                    },
                    markers=[
                        {
                            "time": bar.time,
                            "price": bar.close,
                            "position": "aboveBar" if direction == "BULLISH" else "belowBar",
                            "shape": "arrowUp" if direction == "BULLISH" else "arrowDown",
                            "label": "MSS",
                            "kind": "HIGH" if direction == "BULLISH" else "LOW",
                        }
                    ],
                    coordinates=[(index, bar.close, "SHIFT", "MSS close")],
                    extra={"structure_before": choch.extra.get("structure_before"), "structure_after": direction},
                    source_from_index=choch.source_from_index,
                    family="STRUCTURE",
                )
            )
            break  # one MSS per CHOCH: the first displacement is the shift
    return out
