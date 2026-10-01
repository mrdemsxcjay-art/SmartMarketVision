"""Rectangle (horizontal consolidation) and Support / Resistance levels.

Both build on pivots only - no visual estimation. Support/resistance clustering
is also what the future price-action engine will consume.
"""

from __future__ import annotations

from app.patterns.confidence import score
from app.patterns.geometry import cluster_levels, fit_line
from app.patterns.models import BarContext, Candidate
from app.patterns.params import PatternParams
from app.patterns.pivots import pips, size_threshold


def _fmt(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def _level_strength(touch_count: int, reaction_atr: float, atr: float, recent_bars: int, max_touch: int) -> tuple[float, list[str]]:
    """Measurable strength: touches, real reaction, recency, compactness.

    Returns a 0-100 score plus the detail lines. Each component is a normalised
    ratio, so the score is reproducible from the same pivots.
    """
    touch_component = min(1.0, touch_count / max(2, max_touch)) * 40.0
    reaction_component = min(1.0, reaction_atr / 2.0) * 35.0
    recency_component = max(0.0, 1.0 - recent_bars / 150.0) * 25.0
    strength = round(touch_component + reaction_component + recency_component, 1)
    details = [
        f"touches {touch_count} -> {touch_component:.1f}/40",
        f"reaction {reaction_atr:.2f} ATR -> {reaction_component:.1f}/35",
        f"anciennete {recent_bars} bougies -> {recency_component:.1f}/25",
    ]
    return min(100.0, strength), details


def detect_rectangle(context: BarContext, params: PatternParams) -> list[Candidate]:
    """Horizontal resistance + horizontal support with several real touches."""
    cfg = params.rectangle
    tolerance = size_threshold(
        cfg.horizontal_tolerance_pips, cfg.horizontal_tolerance_atr, context.pip_size, context.size_atr
    )
    highs = [p for p in context.pivots if p.is_high]
    lows = [p for p in context.pivots if not p.is_high]
    if len(highs) < cfg.min_touches_per_side or len(lows) < cfg.min_touches_per_side:
        return []

    candidates: list[Candidate] = []
    # consider the last N highs / lows to allow several rectangle sizes
    for high_window in (5, 4, 3):
        for low_window in (5, 4, 3):
            selected_highs = highs[-high_window:]
            selected_lows = lows[-low_window:]
            if len(selected_highs) < cfg.min_touches_per_side or len(selected_lows) < cfg.min_touches_per_side:
                continue
            upper = fit_line(selected_highs, kind="UPPER")
            lower = fit_line(selected_lows, kind="LOWER")
            if upper is None or lower is None:
                continue

            # horizontality: per-bar slope must be small compared with the box height
            height = upper.intercept - lower.intercept
            if height <= 0:
                continue
            min_height = size_threshold(cfg.min_height_pips, cfg.min_height_atr, context.pip_size, context.size_atr)
            if height < min_height:
                continue
            # horizontality is measured on the whole span: a "flat" level must
            # not drift by more than the touch tolerance across the box (a rising
            # support belongs to a triangle, not to a rectangle)
            span_guess = max(selected_highs[-1].index, selected_lows[-1].index) - min(
                selected_highs[0].index, selected_lows[0].index
            )
            drift_up = abs(upper.slope_per_bar) * span_guess
            drift_low = abs(lower.slope_per_bar) * span_guess
            flat_limit = tolerance
            if drift_up > flat_limit or drift_low > flat_limit:
                continue

            upper_touches = [p for p in selected_highs if abs(p.price - upper.value_at(p.index)) <= tolerance]
            lower_touches = [p for p in selected_lows if abs(p.price - lower.value_at(p.index)) <= tolerance]
            if len(upper_touches) < cfg.min_touches_per_side or len(lower_touches) < cfg.min_touches_per_side:
                continue

            start = min(min(p.index for p in upper_touches), min(p.index for p in lower_touches))
            end = max(max(p.index for p in upper_touches), max(p.index for p in lower_touches))
            span = end - start
            if span < cfg.min_bars or span > cfg.max_bars:
                continue

            resistance = sum(p.price for p in upper_touches) / len(upper_touches)
            support = sum(p.price for p in lower_touches) / len(lower_touches)
            box_height = resistance - support
            if box_height <= 0:
                continue

            # rejection quality: pivots must be real turns (measured by neighbour range)
            reactions = [
                max(
                    abs(context.candles[p.index].high - context.candles[p.index].low),
                    abs(p.price - context.candles[max(0, p.index - 1)].close),
                )
                for p in upper_touches + lower_touches
            ]
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0.0

            evidence = [
                f"Resistance : {_fmt(resistance, context.digits)} "
                f"({len(upper_touches)} touches : "
                f"{', '.join(_fmt(p.price, context.digits) for p in upper_touches)})",
                f"Support : {_fmt(support, context.digits)} "
                f"({len(lower_touches)} touches : "
                f"{', '.join(_fmt(p.price, context.digits) for p in lower_touches)})",
                f"Hauteur de la zone : {pips(box_height, context.pip_size):.1f} pips "
                f"(minimum {pips(min_height, context.pip_size):.1f})",
                f"Horizontality : derive {pips(drift_up, context.pip_size):.1f} / "
                f"{pips(drift_low, context.pip_size):.1f} pips sur {span} bougies "
                f"(limite {pips(flat_limit, context.pip_size):.1f} pips)",
                f"Duree : {span} bougies (min {cfg.min_bars}, max {cfg.max_bars})",
                f"Reaction moyenne des pivots : {pips(avg_reaction, context.pip_size):.1f} pips",
                "Statut : consolidation horizontale en cours",
            ]
            factors = [
                ("Nombre de touches", len(upper_touches) + len(lower_touches) >= 2 * cfg.min_touches_per_side,
                 params.weights.level_quality, f"{len(upper_touches)} haut / {len(lower_touches)} bas"),
                ("Niveau de resistance coherent", upper.r2 >= 0.5, params.weights.structure_clear,
                 f"R2 {upper.r2:.2f}, dispersion {pips(max(p.price for p in upper_touches) - min(p.price for p in upper_touches), context.pip_size):.1f} pips"),
                ("Niveau de support coherent", lower.r2 >= 0.5, params.weights.structure_clear,
                 f"R2 {lower.r2:.2f}"),
                ("Hauteur exploitable", box_height >= min_height * 1.2, params.weights.volume_or_time,
                 f"{pips(box_height, context.pip_size):.1f} pips"),
                ("Duree suffisante", span >= cfg.min_bars * 1.5, params.weights.symmetry,
                 f"{span} bougies"),
                ("Reactions reelles des pivots", avg_reaction >= 0.3 * context.size_atr if context.size_atr else True,
                 params.weights.no_conflict, f"{pips(avg_reaction, context.pip_size):.1f} pips"),
            ]
            confidence, _ = score(factors)

            candidates.append(
                Candidate(
                    pattern="RECTANGLE",
                    direction="NEUTRAL",
                    pivots=sorted(upper_touches + lower_touches, key=lambda p: p.index),
                    evidence=evidence + [f"Confiance : {confidence}%"],
                    evidence_points={
                        "pattern": "RECTANGLE",
                        "support_price": support,
                        "resistance_price": resistance,
                        "touches_support": [p.as_dict() for p in lower_touches],
                        "touches_resistance": [p.as_dict() for p in upper_touches],
                        "resistance_line": {
                            "from": {"time": context.candles[start].time, "price": upper.value_at(start)},
                            "to": {"time": context.candles[end].time, "price": upper.value_at(end)},
                        },
                        "support_line": {
                            "from": {"time": context.candles[start].time, "price": lower.value_at(start)},
                            "to": {"time": context.candles[end].time, "price": lower.value_at(end)},
                        },
                        "pivots": {
                            **{f"RESISTANCE_{i + 1}": p for i, p in enumerate(upper_touches)},
                            **{f"SUPPORT_{i + 1}": p for i, p in enumerate(lower_touches)},
                        },
                        "roles": {f"RESISTANCE_{i + 1}": "R" for i in range(len(upper_touches))}
                        | {f"SUPPORT_{i + 1}": "S" for i in range(len(lower_touches))},
                        "measurements": {
                            "height_pips": round(pips(box_height, context.pip_size), 1),
                            "drift_upper_pips": round(pips(drift_up, context.pip_size), 1),
                            "drift_lower_pips": round(pips(drift_low, context.pip_size), 1),
                            "touches_support": len(lower_touches),
                            "touches_resistance": len(upper_touches),
                            "span_bars": span,
                            "avg_reaction_pips": round(pips(avg_reaction, context.pip_size), 1),
                        },
                    },
                    factors=factors,
                    parameters={**cfg.model_dump(), "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10)},
                    levels={
                        "SUPPORT": support,
                        "RESISTANCE": resistance,
                    },
                    lines=[upper, lower],
                    zones=[
                        {
                            "time_start": context.candles[start].time,
                            "time_end": context.candles[end].time,
                            "price_top": resistance,
                            "price_bottom": support,
                            "label": "CONSOLIDATION",
                            "kind": "RECTANGLE",
                        }
                    ],
                    breakout_levels=[
                        ("RESISTANCE", resistance, "BULLISH"),
                        ("SUPPORT", support, "BEARISH"),
                    ],
                    detected_at_bar_time=context.candles[min(end + 1, len(context.candles) - 1)].time,
                    watch_from_index=end + 1,
                    max_bars_to_confirm=cfg.max_bars_to_confirm,
                )
            )
            return candidates

    return candidates


def detect_support_resistance(context: BarContext, params: PatternParams) -> list[Candidate]:
    """Levels built by clustering real pivot highs / lows."""
    cfg = params.levels
    tolerance = size_threshold(
        cfg.cluster_tolerance_pips, cfg.cluster_tolerance_atr, context.pip_size, context.size_atr
    )
    candidates: list[Candidate] = []

    for kind, pattern, direction in (("HIGH", "RESISTANCE", "BEARISH"), ("LOW", "SUPPORT", "BULLISH")):
        clusters = cluster_levels(
            context.pivots, tolerance=tolerance, kind=kind, min_touches=cfg.min_touches
        )
        for cluster in clusters[: cfg.max_levels]:
            pivots = list(cluster["pivots"])
            price = float(cluster["price"])
            touch_count = int(cluster["touch_count"])
            last_index = int(cluster["last_touch_index"])
            recent_bars = context.last_index - last_index

            # reaction measured from real candles after each touch
            reactions = []
            for pivot in pivots:
                window = context.candles[pivot.index + 1 : pivot.index + 6]
                if not window:
                    continue
                extreme = min(c.low for c in window) if pivot.is_high else max(c.high for c in window)
                reactions.append(abs(pivot.price - extreme))
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0.0
            reaction_atr = avg_reaction / context.size_atr if context.size_atr else 0.0

            # a level the market has already closed beyond is history, not a level
            breached = _closes_beyond(context, price, pattern, last_index)
            if breached > cfg.max_closes_beyond:
                continue
            # neither is a level nobody has traded for a very long time
            recent_bars = context.last_index - last_index
            if recent_bars > cfg.max_bars_since_touch:
                continue

            strength, strength_details = _level_strength(
                touch_count, reaction_atr, context.size_atr, recent_bars, max_touch=6
            )

            breakout_direction = "BULLISH" if pattern == "RESISTANCE" else "BEARISH"
            evidence = [
                f"{'Resistance' if pattern == 'RESISTANCE' else 'Support'} a {_fmt(price, context.digits)}",
                f"Nombre de touches : {touch_count} "
                f"({', '.join(_fmt(p.price, context.digits) for p in pivots)})",
                f"Premiere touche : {pivots[0].iso}",
                f"Derniere touche : {pivots[-1].iso} (il y a {recent_bars} bougies)",
                f"Dispersion des touches : {pips(float(cluster['spread']), context.pip_size):.1f} pips "
                f"(tolerance {pips(tolerance, context.pip_size):.1f})",
                f"Reaction moyenne apres touche : {pips(avg_reaction, context.pip_size):.1f} pips "
                f"({reaction_atr:.2f} ATR)",
                f"Solidite : {strength}/100",
            ]
            factors = [
                ("Touches multiples", touch_count >= 2, params.weights.level_quality, f"{touch_count} touches"),
                ("Reaction reelle", reaction_atr >= cfg.reaction_min_atr, params.weights.structure_clear,
                 f"{reaction_atr:.2f} ATR (minimum {cfg.reaction_min_atr})"),
                ("Touches regroupees", float(cluster["spread"]) <= tolerance, params.weights.symmetry,
                 f"{pips(float(cluster['spread']), context.pip_size):.1f} pips"),
                ("Niveau encore d'actualite", recent_bars <= cfg.max_bars_since_touch, params.weights.volume_or_time,
                 f"{recent_bars} bougies depuis la derniere touche (max {cfg.max_bars_since_touch})"),
                ("Niveau non depasse durablement", breached <= cfg.max_closes_beyond,
                 params.weights.no_conflict,
                 f"{breached} cloture(s) au-dela du niveau (max {cfg.max_closes_beyond})"),
                ("Solidite suffisante", strength >= 45, params.weights.level_quality, f"{strength}/100"),
            ]
            confidence, _ = score(factors)

            candidates.append(
                Candidate(
                    pattern=pattern,
                    direction=direction,
                    pivots=pivots,
                    evidence=evidence + [f"Confiance : {confidence}%", f"Detail solidite : {'; '.join(strength_details)}"],
                    evidence_points={
                        "pattern": pattern,
                        "price": price,
                        "touch_count": touch_count,
                        "first_touch": {"time": int(cluster["first_touch"]), "index": int(cluster["first_touch_index"])},
                        "last_touch": {"time": int(cluster["last_touch"]), "index": int(cluster["last_touch_index"])},
                        "strength": strength,
                        "strength_details": strength_details,
                        "touches": [p.as_dict() for p in pivots],
                        "reaction_avg_pips": round(pips(avg_reaction, context.pip_size), 1),
                        "pivots": {f"TOUCH_{i + 1}": p for i, p in enumerate(pivots)},
                        "roles": {f"TOUCH_{i + 1}": "T" for i in range(len(pivots))},
                        "measurements": {
                            "touch_count": touch_count,
                            "spread_pips": round(pips(float(cluster["spread"]), context.pip_size), 1),
                            "recent_bars": recent_bars,
                            "reaction_atr": round(reaction_atr, 3),
                            "strength": strength,
                        },
                    },
                    factors=factors,
                    parameters={**cfg.model_dump(), "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10)},
                    levels={pattern: price},
                    breakout_levels=[(pattern, price, breakout_direction)],
                    invalidation_level=None,
                    detected_at_bar_time=context.candles[last_index].time,
                    watch_from_index=last_index + 1,
                    max_bars_to_confirm=None,
                )
            )

    return candidates


def _closes_beyond(context: BarContext, price: float, pattern: str, last_index: int) -> int:
    """How many closed bars sit decisively beyond the level (no wick counting)."""
    buffer = 2 * context.pip_size
    if pattern == "RESISTANCE":
        return sum(1 for c in context.candles[last_index + 1 :] if c.close > price + buffer)
    return sum(1 for c in context.candles[last_index + 1 :] if c.close < price - buffer)
