"""Reversal formations: Double Top / Double Bottom / Head & Shoulders / Inverse H&S.

Every condition is measurable and recorded in the evidence, so a detection can be
re-read and re-checked later from the same OHLC and parameters.
"""

from __future__ import annotations

from app.patterns.confidence import score
from app.patterns.geometry import fit_line
from app.patterns.models import BarContext, Candidate, Pivot
from app.patterns.params import PatternParams
from app.patterns.pivots import pips, size_threshold


def _fmt_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def _fmt_pips(value: float, pip: float) -> str:
    return f"{pips(value, pip):.1f} pips"


def detect_double_top(context: BarContext, params: PatternParams) -> list[Candidate]:
    return _detect_double(context, params, kind="TOP")


def detect_double_bottom(context: BarContext, params: PatternParams) -> list[Candidate]:
    return _detect_double(context, params, kind="BOTTOM")


def _detect_double(context: BarContext, params: PatternParams, kind: str) -> list[Candidate]:
    """Two same-kind extremes separated by a real reaction, with a neckline.

    Nothing is detected unless: two pivots of the same kind, a minimum time
    separation, a price difference inside tolerance, an intermediate opposite
    pivot whose depth clears the minimum, and no intervening pivot exceeding the
    pair (which would make it a trend, not a double top/bottom).
    """
    cfg = params.double_top_bottom
    is_top = kind == "TOP"
    pattern = "DOUBLE_TOP" if is_top else "DOUBLE_BOTTOM"
    direction = "BEARISH" if is_top else "BULLISH"
    extreme_kind = "HIGH" if is_top else "LOW"
    reaction_kind = "LOW" if is_top else "HIGH"

    extremes = [p for p in context.pivots if p.kind == extreme_kind]
    if len(extremes) < 2:
        return []

    tolerance = size_threshold(cfg.peak_tolerance_pips, cfg.peak_tolerance_atr, context.pip_size, context.size_atr)
    min_depth = size_threshold(
        cfg.min_valley_depth_pips, cfg.min_valley_depth_atr, context.pip_size, context.size_atr
    )
    buffer_confirm = cfg.confirmation_buffer_pips * context.pip_size
    buffer_invalidate = cfg.invalidation_buffer_pips * context.pip_size

    candidates: list[Candidate] = []
    for first, second in zip(extremes, extremes[1:]):
        separation = second.index - first.index
        if separation < cfg.min_peak_separation_bars or separation > cfg.max_peak_separation_bars:
            continue

        between = [p for p in context.pivots if first.index < p.index < second.index]
        reactions = [p for p in between if p.kind == reaction_kind]
        if not reactions:
            continue
        reaction = min(reactions, key=lambda p: p.price) if is_top else max(reactions, key=lambda p: p.price)

        price_diff = abs(second.price - first.price)
        if price_diff > tolerance:
            continue

        depth = (min(first.price, second.price) - reaction.price) if is_top else (reaction.price - max(first.price, second.price))
        if depth < min_depth:
            continue

        # The reaction must be a real correction of the leg that led to the first
        # extreme - measured from the last opposite swing before it, and never
        # from an arbitrary window extreme.
        prior_swing = next(
            (p for p in reversed(context.pivots) if p.kind == reaction_kind and p.index < first.index), None
        )
        prior_leg = 0.0
        if prior_swing is not None:
            prior_leg = (
                first.price - prior_swing.price if is_top else prior_swing.price - first.price
            )
        ratio_ok = prior_leg <= 0 or depth >= cfg.min_valley_depth_ratio * prior_leg
        if not ratio_ok:
            continue

        # An intervening pivot beyond the pair means the pattern is not clean.
        intervening = [p for p in between if p.kind == extreme_kind]
        intervening_extreme = (
            max((p.price for p in intervening), default=0.0)
            if is_top
            else min((p.price for p in intervening), default=float("inf"))
        )
        exceeds = (
            intervening_extreme > max(first.price, second.price) + tolerance
            if is_top
            else intervening_extreme < min(first.price, second.price) - tolerance
        )
        if cfg.forbid_intervening_extreme and intervening and exceeds:
            continue

        # the formation must be recent: a 2024 double top is not a signal today
        if context.last_index - second.index > cfg.max_bars_since_formation:
            continue

        # symmetry of the two halves of the formation
        span_first = reaction.index - first.index
        span_second = second.index - reaction.index
        symmetry_ratio = max(span_first, span_second) / max(1, min(span_first, span_second))

        neckline = reaction.price
        watch_from = second.confirmed_at_index

        evidence = [
            f"{'Peak' if is_top else 'Trough'} 1 : {_fmt_price(first.price, context.digits)} "
            f"(barre {first.index}, {first.iso})",
            f"{'Peak' if is_top else 'Trough'} 2 : {_fmt_price(second.price, context.digits)} "
            f"(barre {second.index}, {second.iso})",
            f"Ecart entre les deux : {pips(price_diff, context.pip_size):.2f} pip "
            f"(tolerance {pips(tolerance, context.pip_size):.2f} pip)",
            f"{'Creux' if is_top else 'Sommet'} intermediaire : {_fmt_price(reaction.price, context.digits)} "
            f"(barre {reaction.index})",
            f"Profondeur : {_fmt_pips(depth, context.pip_size)} "
            f"(minimum {pips(min_depth, context.pip_size):.1f} pips)",
            f"Separation temporelle : {separation} bougies "
            f"(min {cfg.min_peak_separation_bars}, max {cfg.max_peak_separation_bars})",
            f"Neckline : {_fmt_price(neckline, context.digits)}",
            f"Symetrie des deux moities : rapport {symmetry_ratio:.2f} (max {cfg.symmetry_max_ratio})",
            f"Pivots opposes intermediaires : {len(intervening)} sans depassement"
            if intervening
            else "Aucun pivot extreme intermediaire",
            f"Statut : formation complete, breakout non encore observe",
        ]

        factors = [
            ("Proximite des deux extremes", price_diff <= tolerance * 0.5, params.weights.structure_clear,
             f"ecart {pips(price_diff, context.pip_size):.2f} pip vs tolerance {pips(tolerance, context.pip_size):.2f} pip"),
            ("Profondeur suffisante", depth >= min_depth * 1.5, params.weights.level_quality,
             f"{pips(depth, context.pip_size):.1f} pips vs minimum {pips(min_depth, context.pip_size):.1f} pips"),
            ("Reaction proportionnee a la jambe precedente",
             ratio_ok, params.weights.symmetry,
             f"creux {pips(depth, context.pip_size):.1f} pips vs "
             f"{cfg.min_valley_depth_ratio * 100:.0f}% de {pips(prior_leg, context.pip_size):.1f} pips"),
            ("Symetrie des deux moities", symmetry_ratio <= cfg.symmetry_max_ratio, params.weights.symmetry,
             f"rapport {symmetry_ratio:.2f}"),
            ("Duree de formation dans la bande ideale",
             cfg.min_peak_separation_bars * 2 <= separation <= cfg.max_peak_separation_bars * 0.6,
             params.weights.volume_or_time, f"{separation} bougies"),
            ("Aucun depassement intermediaire", not intervening or not exceeds, params.weights.no_conflict,
             f"{len(intervening)} pivot(s) extreme(s) entre les deux"),
            ("Neckline exploitable", depth > 0, params.weights.level_quality,
             f"neckline {_fmt_price(neckline, context.digits)}"),
        ]
        confidence, factor_details = score(factors)

        candidate = Candidate(
            pattern=pattern,
            direction=direction,
            pivots=[first, reaction, second],
            evidence=evidence,
            evidence_points={
                "pattern": pattern,
                "peak_1": first.as_dict(),
                "peak_2": second.as_dict(),
                "valley": reaction.as_dict(),
                "neckline": {
                    "price": neckline,
                    "type": "NECKLINE",
                    "description": "ligne horizontale au niveau du creux" if is_top
                    else "ligne horizontale au niveau du sommet",
                },
                "pivots": {
                    "PEAK_1" if is_top else "TROUGH_1": first,
                    "REACTION" if is_top else "REACTION": reaction,
                    "PEAK_2" if is_top else "TROUGH_2": second,
                },
                "roles": {
                    "PEAK_1" if is_top else "TROUGH_1": "S1" if is_top else "C1",
                    "REACTION": "CREUX" if is_top else "SOMMET",
                    "PEAK_2" if is_top else "TROUGH_2": "S2" if is_top else "C2",
                },
                "measurements": {
                    "price_difference_pips": round(pips(price_diff, context.pip_size), 2),
                    "tolerance_pips": round(pips(tolerance, context.pip_size), 2),
                    "depth_pips": round(pips(depth, context.pip_size), 1),
                    "min_depth_pips": round(pips(min_depth, context.pip_size), 1),
                    "prior_leg_pips": round(pips(prior_leg, context.pip_size), 1),
                    "depth_ratio": round(depth / prior_leg, 3) if prior_leg else 0.0,
                    "time_separation_bars": separation,
                    "symmetry_ratio": round(symmetry_ratio, 2),
                },
            },
            factors=factors,
            parameters={
                "peak_tolerance_pips": cfg.peak_tolerance_pips,
                "peak_tolerance_atr": cfg.peak_tolerance_atr,
                "resolved_tolerance_price": round(tolerance, 10),
                "min_valley_depth_pips": cfg.min_valley_depth_pips,
                "min_valley_depth_ratio": cfg.min_valley_depth_ratio,
                "prior_leg_pips": round(pips(prior_leg, context.pip_size), 1),
                "prior_swing_index": prior_swing.index if prior_swing is not None else None,
                "min_depth_price": round(min_depth, 10),
                "min_peak_separation_bars": cfg.min_peak_separation_bars,
                "max_peak_separation_bars": cfg.max_peak_separation_bars,
                "confirmation_buffer_pips": cfg.confirmation_buffer_pips,
                "pivot_left": params.globals.pivot_left,
                "pivot_right": params.globals.pivot_right,
                "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10),
                "confidence_factors": [criterion for criterion, _, _, _ in factors],
            },
            levels={
                "NECKLINE": neckline,
                f"{'PEAK' if is_top else 'TROUGH'}_1": first.price,
                f"{'PEAK' if is_top else 'TROUGH'}_2": second.price,
            },
            breakout_levels=[
                ("NECKLINE", neckline, direction),
                (
                    "PEAK" if is_top else "TROUGH",
                    max(first.price, second.price) if is_top else min(first.price, second.price),
                    "BULLISH" if is_top else "BEARISH",
                ),
            ],
            invalidation_level=(
                max(first.price, second.price) + buffer_invalidate
                if is_top
                else min(first.price, second.price) - buffer_invalidate
            ),
            invalidation_level_type="PEAK_BROKEN" if is_top else "TROUGH_BROKEN",
            invalidation_reason=(
                "cloture au-dessus des deux sommets (nouveau plus haut)"
                if is_top
                else "cloture sous les deux creux (nouveau plus bas)"
            ),
            detected_at_bar_time=(
                context.candles[watch_from].time if watch_from < len(context.candles) else second.time
            ),
            watch_from_index=watch_from,
            max_bars_to_confirm=cfg.max_bars_to_confirm,
            notes=[
                f"confirmation attendue : cloture {'sous' if is_top else 'au-dessus'} de la neckline "
                f"{_fmt_price(neckline, context.digits)} (+/- {buffer_confirm / context.pip_size:.1f} pip de marge)"
            ],
        )
        candidate.evidence = evidence + [f"Confiance : {confidence}%"]
        candidates.append(candidate)

    return _deduplicate_by_second_extreme(candidates)


def _deduplicate_by_second_extreme(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the best candidate per second extreme (avoids nested duplicates)."""
    best: dict[int, Candidate] = {}
    for candidate in candidates:
        key = candidate.pivots[-1].index
        current = best.get(key)
        if current is None or len(candidate.evidence) > len(current.evidence):
            best[key] = candidate
    return sorted(best.values(), key=lambda c: c.pivots[-1].index)


def detect_head_shoulders(context: BarContext, params: PatternParams) -> list[Candidate]:
    return _detect_head_shoulders(context, params, inverse=False)


def detect_inverse_head_shoulders(context: BarContext, params: PatternParams) -> list[Candidate]:
    return _detect_head_shoulders(context, params, inverse=True)


def _detect_head_shoulders(context: BarContext, params: PatternParams, inverse: bool) -> list[Candidate]:
    """5 alternating pivots: LS - valley - HEAD - valley - RS (inverted for inverse)."""
    cfg = params.head_shoulders
    pattern = "INVERSE_HEAD_SHOULDERS" if inverse else "HEAD_SHOULDERS"
    direction = "BULLISH" if inverse else "BEARISH"
    extreme_kind = "LOW" if inverse else "HIGH"
    reaction_kind = "HIGH" if inverse else "LOW"

    pivots = context.pivots
    if len(pivots) < 5:
        return []

    shoulder_tolerance = size_threshold(
        cfg.shoulder_tolerance_pips, cfg.shoulder_tolerance_atr, context.pip_size, context.size_atr
    )
    head_prominence = size_threshold(
        cfg.head_min_prominence_pips, cfg.head_min_prominence_atr, context.pip_size, context.size_atr
    )
    min_depth = size_threshold(cfg.min_valley_depth_pips, cfg.min_valley_depth_atr, context.pip_size, context.size_atr)
    neckline_slope_limit = cfg.neckline_max_slope_atr_per_bar * context.size_atr

    candidates: list[Candidate] = []
    for start in range(len(pivots) - 4):
        window = pivots[start : start + 5]
        kinds = [p.kind for p in window]
        if kinds != [extreme_kind, reaction_kind, extreme_kind, reaction_kind, extreme_kind]:
            continue

        left_shoulder, valley_1, head, valley_2, right_shoulder = window
        bearing = 1 if not inverse else -1  # +1 when higher prices are "more extreme"

        def extr(value: float) -> float:
            return value * bearing

        # head must dominate both shoulders
        prominence = extr(head.price) - max(extr(left_shoulder.price), extr(right_shoulder.price))
        if prominence < head_prominence:
            continue

        # shoulders must be comparable
        shoulder_diff = abs(right_shoulder.price - left_shoulder.price)
        if shoulder_diff > shoulder_tolerance:
            continue

        # valleys must react far enough from the shoulders/head
        valley_extreme = max(extr(valley_1.price), extr(valley_2.price))
        depth = min(extr(left_shoulder.price), extr(right_shoulder.price)) - valley_extreme
        if depth < min_depth:
            continue

        # neckline through the two valleys
        neckline = fit_line([valley_1, valley_2], kind="NECKLINE")
        if neckline is None:
            continue
        if abs(neckline.slope_per_bar) > neckline_slope_limit:
            continue

        total_bars = right_shoulder.index - left_shoulder.index
        if total_bars > cfg.max_total_bars:
            continue

        neckline_at_shoulder = neckline.value_at(right_shoulder.index)
        # the head must be beyond the neckline on the extreme side (above for a
        # classic H&S, below for an inverse one) - expressed in extreme space
        head_beyond_neckline = extr(head.price) - extr(neckline.value_at(head.index))
        if head_beyond_neckline <= 0:
            continue

        if context.last_index - right_shoulder.index > cfg.max_bars_since_formation:
            continue

        # trend context: a classic H&S tops an advance, an inverse H&S bottoms a fall
        trend_min = size_threshold(cfg.trend_min_pips, cfg.trend_min_atr, context.pip_size, context.size_atr)
        context_bars = context.candles[max(0, left_shoulder.index - cfg.trend_lookback_bars) : left_shoulder.index]
        prior_move = 0.0
        if context_bars:
            if not inverse:
                prior_move = left_shoulder.price - min(c.low for c in context_bars)
            else:
                prior_move = max(c.high for c in context_bars) - left_shoulder.price
        if cfg.require_trend_context and prior_move < trend_min:
            continue

        slope_pips_per_bar = neckline.slope_per_bar / context.pip_size

        evidence = [
            f"{'Epaule gauche' if not inverse else 'Epaule gauche (inversee)'} : {_fmt_price(left_shoulder.price, context.digits)} (barre {left_shoulder.index})",
            f"{'Tete' if not inverse else 'Tete (creux)'} : {_fmt_price(head.price, context.digits)} (barre {head.index})",
            f"Epaule droite : {_fmt_price(right_shoulder.price, context.digits)} (barre {right_shoulder.index})",
            f"Tete plus marquee que les epaules de {_fmt_pips(prominence, context.pip_size)} "
            f"(minimum {pips(head_prominence, context.pip_size):.1f} pips)",
            f"Ecart entre les deux epaules : {_fmt_pips(shoulder_diff, context.pip_size)} "
            f"(tolerance {pips(shoulder_tolerance, context.pip_size):.1f} pips)",
            f"Creux intermediaires : {_fmt_price(valley_1.price, context.digits)} / {_fmt_price(valley_2.price, context.digits)}",
            f"Neckline : de {_fmt_price(neckline.value_at(valley_1.index), context.digits)} a "
            f"{_fmt_price(neckline.value_at(valley_2.index), context.digits)} "
            f"(pente {slope_pips_per_bar:.2f} pip/bougie)",
            f"Neckline a l'epaule droite : {_fmt_price(neckline_at_shoulder, context.digits)}",
            f"Duree totale : {total_bars} bougies (max {cfg.max_total_bars})",
            f"Contexte : {'avancee' if not inverse else 'baisse'} de {_fmt_pips(prior_move, context.pip_size)} "
            f"avant l'epaule gauche (minimum {pips(trend_min, context.pip_size):.1f} pips)",
        ]

        factors = [
            ("Tete dominante", prominence >= head_prominence, params.weights.structure_clear,
             f"{pips(prominence, context.pip_size):.1f} pips vs minimum {pips(head_prominence, context.pip_size):.1f}"),
            ("Epaules comparables", shoulder_diff <= shoulder_tolerance * 0.6, params.weights.symmetry,
             f"{pips(shoulder_diff, context.pip_size):.1f} pips"),
            ("Reactions profondes", depth >= min_depth * 1.3, params.weights.level_quality,
             f"{pips(depth, context.pip_size):.1f} pips"),
            ("Neckline exploitable", abs(neckline.slope_per_bar) <= neckline_slope_limit * 0.5, params.weights.level_quality,
             f"pente {slope_pips_per_bar:.2f} pip/bougie"),
            ("Duree dans la bande ideale", total_bars <= cfg.max_total_bars * 0.7, params.weights.volume_or_time,
             f"{total_bars} bougies"),
            ("Tete au dela de la neckline", head_beyond_neckline > 0, params.weights.no_conflict,
             f"{_fmt_pips(head_beyond_neckline, context.pip_size)}"),
            ("Contexte de tendance avant l'epaule gauche", prior_move >= trend_min, params.weights.no_conflict,
             f"{_fmt_pips(prior_move, context.pip_size)} vs minimum {pips(trend_min, context.pip_size):.1f} pips"),
        ]
        confidence, _ = score(factors)

        candidates.append(
            Candidate(
                pattern=pattern,
                direction=direction,
                pivots=list(window),
                evidence=evidence + [f"Confiance : {confidence}%"],
                evidence_points={
                    "pattern": pattern,
                    "left_shoulder": left_shoulder.as_dict(),
                    "head": head.as_dict(),
                    "right_shoulder": right_shoulder.as_dict(),
                    "valley_1": valley_1.as_dict(),
                    "valley_2": valley_2.as_dict(),
                    "neckline": {
                        "from": {"time": valley_1.time, "price": neckline.value_at(valley_1.index)},
                        "to": {"time": valley_2.time, "price": neckline.value_at(valley_2.index)},
                        "slope_per_bar": neckline.slope_per_bar,
                        "value_at_right_shoulder": neckline_at_shoulder,
                    },
                    "pivots": {
                        "LEFT_SHOULDER": left_shoulder,
                        "VALLEY_1": valley_1,
                        "HEAD": head,
                        "VALLEY_2": valley_2,
                        "RIGHT_SHOULDER": right_shoulder,
                    },
                    "roles": {
                        "LEFT_SHOULDER": "EG",
                        "VALLEY_1": "C1",
                        "HEAD": "TETE",
                        "VALLEY_2": "C2",
                        "RIGHT_SHOULDER": "ED",
                    },
                    "measurements": {
                        "prior_trend_pips": round(pips(prior_move, context.pip_size), 1),
                        "head_prominence_pips": round(pips(prominence, context.pip_size), 1),
                        "shoulder_difference_pips": round(pips(shoulder_diff, context.pip_size), 1),
                        "valley_depth_pips": round(pips(depth, context.pip_size), 1),
                        "neckline_slope_pips_per_bar": round(slope_pips_per_bar, 3),
                        "total_bars": total_bars,
                    },
                },
                factors=factors,
                parameters={
                    "shoulder_tolerance_pips": cfg.shoulder_tolerance_pips,
                    "head_min_prominence_pips": cfg.head_min_prominence_pips,
                    "min_valley_depth_pips": cfg.min_valley_depth_pips,
                    "neckline_max_slope_atr_per_bar": cfg.neckline_max_slope_atr_per_bar,
                    "confirmation_buffer_pips": cfg.confirmation_buffer_pips,
                    "pivot_left": params.globals.pivot_left,
                    "pivot_right": params.globals.pivot_right,
                    "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10),
                },
                levels={"NECKLINE": neckline_at_shoulder, "HEAD": head.price},
                lines=[neckline],
                breakout_levels=[
                    ("NECKLINE", neckline_at_shoulder, direction),
                    ("HEAD", head.price, "BULLISH" if not inverse else "BEARISH"),
                ],
                invalidation_level=head.price + (cfg.invalidation_buffer_pips * context.pip_size) * bearing,
                invalidation_level_type="HEAD_BROKEN",
                invalidation_reason=(
                    "cloture au-dessus de la tete" if not inverse else "cloture sous la tete"
                ),
                detected_at_bar_time=(
                    context.candles[right_shoulder.confirmed_at_index].time
                    if right_shoulder.confirmed_at_index < len(context.candles)
                    else right_shoulder.time
                ),
                watch_from_index=right_shoulder.confirmed_at_index,
                max_bars_to_confirm=cfg.max_bars_to_confirm,
                notes=[
                    f"confirmation attendue : cloture {'sous' if not inverse else 'au-dessus'} de la neckline "
                    f"{_fmt_price(neckline_at_shoulder, context.digits)}"
                ],
            )
        )

    # keep the best candidate per right shoulder
    best: dict[int, Candidate] = {}
    for candidate in candidates:
        best[candidate.pivots[-1].index] = candidate
    return sorted(best.values(), key=lambda c: c.pivots[-1].index)
