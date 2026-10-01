"""Flag and Pennant formations (continuation patterns).

A flag is NOT "any small consolidation". The engine requires, on real data:

1. a **pole** - a real pivot-to-pivot impulse (a LOW to a HIGH for a bull flag,
   the mirror for a bear flag) of at least N ATR (or N pips);
2. a **consolidation** after the pole: at least K bars, no more than a configured
   fraction of the pole retraced, narrow relative to the pole's own volatility,
   and not drifting by more than a fraction of its own height;
3. a **measurable continuation direction** (the pole's direction) and the exact
   breakout level in that direction.

Shape: a FLAG has near-parallel boundaries. A PENNANT requires fitted boundaries
that actually converge - a pennant is never claimed when the internal pivots are
too few to fit two lines.
"""

from __future__ import annotations

from app.patterns.confidence import score
from app.patterns.geometry import fit_line, midpoint_slope, relative_slope_gap, width_at
from app.patterns.models import BarContext, Candidate, Pivot
from app.patterns.params import PatternParams
from app.patterns.pivots import compute_atr, pips, size_threshold


def _fmt(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def detect_flags(context: BarContext, params: PatternParams) -> list[Candidate]:
    cfg = params.flags
    if len(context.pivots) < 4 or len(context.candles) < cfg.consolidation_min_bars + 4:
        return []

    impulse_min = size_threshold(cfg.impulse_min_pips, cfg.impulse_min_atr, context.pip_size, context.size_atr)
    last_index = context.last_index

    for bullish in (True, False):
        pole_kind = "HIGH" if bullish else "LOW"
        for index in range(len(context.pivots) - 1, -1, -1):
            pole = context.pivots[index]
            if pole.kind != pole_kind:
                continue

            cons_len = last_index - pole.index
            if cons_len < cfg.consolidation_min_bars:
                continue  # not a consolidation yet: the move is still running
            if cons_len > cfg.consolidation_max_bars:
                break  # older poles produce even longer consolidations

            origins = [p for p in context.pivots[:index] if p.kind != pole_kind]
            if not origins:
                continue
            origin = origins[-1]  # the pivot the pole started from
            move = pole.price - origin.price
            pole_size = move if bullish else -move
            if pole_size < impulse_min:
                continue

            pole_bars = context.candles[origin.index : pole.index + 1]
            if len(pole_bars) < 3:
                continue
            direction = 1 if bullish else -1
            aligned = sum(1 for b in pole_bars if (b.close - b.open) * direction > 0)
            if aligned / len(pole_bars) < 0.55:
                continue

            # the consolidation starts after the pole's extreme bar
            box_bars = context.candles[pole.index + 1 : last_index + 1]
            if len(box_bars) < cfg.consolidation_min_bars:
                continue
            cons_high = max(c.high for c in box_bars)
            cons_low = min(c.low for c in box_bars)
            cons_width = cons_high - cons_low
            if cons_width <= 0:
                continue

            # the consolidation is sized against the volatility of the pole it
            # corrects: the current ATR collapses inside a quiet box
            pole_atr = compute_atr(pole_bars, period=min(14, max(2, len(pole_bars))))
            width_limit_atr = cfg.max_width_atr * pole_atr if pole_atr else float("inf")
            width_limit_pole = cfg.max_width_pole_ratio * pole_size
            if cons_width > width_limit_atr or cons_width > width_limit_pole:
                continue

            retrace = (pole.price - cons_low) if bullish else (cons_high - pole.price)
            if retrace < 0 or retrace > cfg.max_retrace_ratio * pole_size:
                continue

            internal = [p for p in context.pivots if p.index > pole.index]
            if len(internal) < 2:
                continue  # a box without structure is not a formation

            # ---- shape from the box's own pivots
            highs = [p for p in internal if p.is_high]
            lows = [p for p in internal if not p.is_high]
            upper = fit_line(highs[-4:], kind="UPPER") if len(highs) >= 2 else None
            lower = fit_line(lows[-4:], kind="LOWER") if len(lows) >= 2 else None

            box_start_index = pole.index + 1
            gap: float | None = None
            contraction: float | None = None
            if upper is not None and lower is not None:
                width_start = width_at(upper, lower, box_start_index)
                width_end = width_at(upper, lower, last_index)
                # the boundaries must converge without having crossed yet
                converging = (
                    width_end > 0
                    and width_end < width_start
                    and upper.slope_per_bar < lower.slope_per_bar
                )
                contraction = 1.0 - (width_end / width_start) if width_start > 0 else 0.0
                # the relative gap is meaningless when both lines are flat
                biggest = max(abs(upper.slope_per_bar), abs(lower.slope_per_bar))
                gap = 0.0 if biggest < 0.02 * pole_atr else relative_slope_gap(upper, lower, pole_atr)
                shape = "PENNANT" if converging else "FLAG"
                shape_ok = (contraction >= cfg.min_contraction) if converging else (gap <= cfg.parallel_tolerance)
                box_drift = abs((upper.slope_per_bar + lower.slope_per_bar) / 2) * cons_len
            else:
                shape = "FLAG"  # a pennant always needs two fitted lines
                box_drift = abs(midpoint_slope(box_bars)) * cons_len
                shape_ok = True

            if box_drift > cfg.max_box_drift_ratio * cons_width:
                continue
            if not shape_ok:
                continue

            pattern = f"{'BULL' if bullish else 'BEAR'}_{shape}"
            breakout_level = cons_high if bullish else cons_low
            level_type = "CONSOLIDATION_HIGH" if bullish else "CONSOLIDATION_LOW"
            pole_pips = pips(move, context.pip_size)
            retrace_ratio = retrace / pole_size
            atr_multiple = pole_size / context.size_atr if context.size_atr else 0.0

            evidence = [
                f"Pole (jambe impulsive) : {_fmt(origin.price, context.digits)} ({origin.iso}) -> "
                f"{_fmt(pole.price, context.digits)} ({pole.iso}) en {len(pole_bars)} bougies "
                f"({pole_pips:.1f} pips, {atr_multiple:.2f} ATR)",
                f"Bougies alignees dans le pole : {aligned}/{len(pole_bars)}",
                f"Consolidation : {cons_len} bougies apres le pole, boite "
                f"{_fmt(cons_low, context.digits)} - {_fmt(cons_high, context.digits)} "
                f"({pips(cons_width, context.pip_size):.1f} pips = "
                f"{cons_width / width_limit_atr * cfg.max_width_atr:.2f} ATR du pole)",
                f"Retracement du pole : {retrace_ratio * 100:.1f}% (max {cfg.max_retrace_ratio * 100:.0f}%)",
                f"Derive de la boite : {pips(box_drift, context.pip_size):.1f} pips sur {cons_len} bougies "
                f"(max {cfg.max_box_drift_ratio * 100:.0f}% de {pips(cons_width, context.pip_size):.1f} pips)",
                f"Forme : {shape}"
                + (
                    f" (contraction {contraction * 100:.1f}%, minimum {cfg.min_contraction * 100:.0f}%)"
                    if shape == "PENNANT"
                    else f" (ecart de pente relatif {gap:.3f}, tolerance {cfg.parallel_tolerance})"
                    if gap is not None
                    else " (pivots internes insuffisants pour ajuster deux lignes)"
                ),
                f"Continuation attendue : {'BULLISH' if bullish else 'BEARISH'} au-dela de "
                f"{_fmt(breakout_level, context.digits)}",
            ]
            factors = [
                ("Pole impulsif reel", pole_size >= impulse_min * 1.3, params.weights.structure_clear,
                 f"{pole_pips:.1f} pips / {atr_multiple:.2f} ATR"),
                ("Pole directionnel", aligned / len(pole_bars) >= 0.6, params.weights.no_conflict,
                 f"{aligned}/{len(pole_bars)} bougies alignees"),
                ("Consolidation assez longue", cons_len >= cfg.consolidation_min_bars * 1.5,
                 params.weights.volume_or_time, f"{cons_len} bougies"),
                ("Retracement limite", retrace_ratio <= cfg.max_retrace_ratio * 0.6, params.weights.symmetry,
                 f"{retrace_ratio * 100:.1f}% vs max {cfg.max_retrace_ratio * 100:.0f}%"),
                ("Consolidation etroite",
                 cons_width <= width_limit_atr * 0.75 and cons_width <= width_limit_pole * 0.75,
                 params.weights.level_quality,
                 f"{pips(cons_width, context.pip_size):.1f} pips vs {pips(width_limit_atr, context.pip_size):.1f} "
                 f"(ATR du pole) et {pips(width_limit_pole, context.pip_size):.1f} (proportion du pole)"),
                ("Derive faible de la boite", box_drift <= cfg.max_box_drift_ratio * cons_width * 0.7,
                 params.weights.structure_clear, f"{pips(box_drift, context.pip_size):.1f} pips"),
                ("Forme coherente (parallele ou convergente)", shape_ok, params.weights.structure_clear,
                 shape + (
                     f", contraction {contraction * 100:.1f}%"
                     if shape == "PENNANT"
                     else f", ecart pente {gap:.3f}"
                     if gap is not None
                     else ""
                 )),
            ]
            confidence, _ = score(factors)

            return [
                Candidate(
                    pattern=pattern,
                    direction="BULLISH" if bullish else "BEARISH",
                    pivots=[origin, pole] + internal,
                    evidence=evidence + [f"Confiance : {confidence}%"],
                    evidence_points={
                        "pattern": pattern,
                        "pole": {
                            "start_time": origin.iso,
                            "start_index": origin.index,
                            "start_price": origin.price,
                            "end_time": pole.iso,
                            "end_index": pole.index,
                            "end_price": pole.price,
                            "bars": len(pole_bars),
                            "pips": round(pole_pips, 1),
                            "atr_multiple": round(atr_multiple, 2),
                        },
                        "consolidation": {
                            "start_time": box_bars[0].iso if hasattr(box_bars[0], "iso") else None,
                            "start_index": box_start_index,
                            "end_index": last_index,
                            "high": cons_high,
                            "low": cons_low,
                            "bars": cons_len,
                            "width_pips": round(pips(cons_width, context.pip_size), 1),
                        },
                        "retracement_ratio": round(retrace_ratio, 4),
                        "shape": shape,
                        "pivots": {
                            "POLE_START": origin.as_dict(),
                            "POLE_END": pole.as_dict(),
                            **{f"CONS_HIGH_{i + 1}": p for i, p in enumerate(highs[-4:])},
                            **{f"CONS_LOW_{i + 1}": p for i, p in enumerate(lows[-4:])},
                        },
                        "roles": {
                            "POLE_START": "O",
                            "POLE_END": "P",
                            **{f"CONS_HIGH_{i + 1}": "H" for i in range(len(highs[-4:]))},
                            **{f"CONS_LOW_{i + 1}": "L" for i in range(len(lows[-4:]))},
                        },
                        "measurements": {
                            "pole_pips": round(pole_pips, 1),
                            "pole_atr_multiple": round(atr_multiple, 2),
                            "pole_atr_pips": round(pips(pole_atr, context.pip_size), 1),
                            "consolidation_bars": cons_len,
                            "consolidation_width_pips": round(pips(cons_width, context.pip_size), 1),
                            "consolidation_width_pole_atr": round(cons_width / pole_atr, 2) if pole_atr else None,
                            "consolidation_width_pole_ratio": round(cons_width / pole_size, 4),
                            "retracement_ratio": round(retrace_ratio, 4),
                            "box_drift_pips": round(pips(box_drift, context.pip_size), 1),
                            "contraction": round(contraction, 4) if upper is not None and lower is not None else None,
                            "slope_gap_relative": round(gap, 4) if gap is not None else None,
                        },
                    },
                    factors=factors,
                    parameters={
                        **cfg.model_dump(),
                        "atr": round(context.atr, 10),
                        "atr_slow": round(context.atr_slow, 10),
                        "pole_atr": round(pole_atr, 10),
                    },
                    levels={
                        "POLE_START": origin.price,
                        "POLE_END": pole.price,
                        "CONSOLIDATION_HIGH": cons_high,
                        "CONSOLIDATION_LOW": cons_low,
                        "BREAKOUT": breakout_level,
                    },
                    lines=[line for line in (upper, lower) if line is not None],
                    zones=[
                        {
                            "time_start": box_bars[0].time,
                            "time_end": box_bars[-1].time,
                            "price_top": cons_high,
                            "price_bottom": cons_low,
                            "label": pattern,
                            "kind": "CONSOLIDATION",
                        }
                    ],
                    breakout_levels=[(level_type, breakout_level, "BULLISH" if bullish else "BEARISH")],
                    invalidation_level=(
                        cons_low - params.breakout.buffer_pips * context.pip_size
                        if bullish
                        else cons_high + params.breakout.buffer_pips * context.pip_size
                    ),
                    invalidation_level_type="CONSOLIDATION_BROKEN_AGAINST",
                    invalidation_reason="cloture du cote oppose a la continuation attendue",
                    detected_at_bar_time=context.candles[last_index].time,
                    watch_from_index=last_index + 1,
                    max_bars_to_confirm=cfg.max_bars_to_confirm,
                )
            ]

    return []
