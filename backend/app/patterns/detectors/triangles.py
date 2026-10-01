"""Triangle, Wedge and Channel formations from real pivots.

Shared idea: take the most recent pivots, fit an upper line through the pivot
highs and a lower line through the pivot lows, then measure:
* how many real pivots touch each line (never fewer than the configured minimum
  and never "a triangle from two points");
* the slopes (horizontal / ascending / descending) in ATR per bar;
* whether the lines converge (triangle / wedge) or stay parallel (channel).
"""

from __future__ import annotations

from app.patterns.confidence import score
from app.patterns.geometry import (
    apex_index,
    count_touches,
    fit_line,
    relative_slope_gap,
    width_at,
    with_touches,
)
from app.patterns.models import BarContext, Candidate, TrendLine
from app.patterns.params import PatternParams
from app.patterns.pivots import pips, size_threshold


def _fmt(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def _classify_slope(slope: float, flat_limit: float) -> str:
    """A boundary is directional as soon as it leaves the horizontal band."""
    if abs(slope) < flat_limit:
        return "HORIZONTAL"
    return "ASCENDING" if slope > 0 else "DESCENDING"


def _build_line_pair(
    highs: list, lows: list, tolerance: float
) -> tuple[TrendLine, TrendLine, list, list] | None:
    """Fit both lines on the most recent pivots and count touches."""
    if len(highs) < 2 or len(lows) < 2:
        return None
    upper = fit_line(highs, kind="UPPER")
    lower = fit_line(lows, kind="LOWER")
    if upper is None or lower is None:
        return None
    upper_touches = count_touches(upper, highs, kind="HIGH", tolerance=tolerance)
    lower_touches = count_touches(lower, lows, kind="LOW", tolerance=tolerance)
    with_touches(upper, upper_touches)
    with_touches(lower, lower_touches)
    return upper, lower, upper_touches, lower_touches


def detect_triangles(context: BarContext, params: PatternParams) -> list[Candidate]:
    """ASCENDING / DESCENDING / SYMMETRICAL triangle."""
    cfg = params.triangle
    candidates: list[Candidate] = []

    for high_count, low_count in ((3, 3), (3, 2), (2, 3), (2, 2)):
        highs = [p for p in context.pivots if p.is_high][-high_count:]
        lows = [p for p in context.pivots if not p.is_high][-low_count:]
        pair = _build_line_pair(highs, lows, size_threshold(
            cfg.touch_tolerance_pips, cfg.touch_tolerance_atr, context.pip_size, context.size_atr
        ))
        if pair is None:
            continue
        upper, lower, upper_touches, lower_touches = pair
        if len(upper_touches) < cfg.min_touches_per_line or len(lower_touches) < cfg.min_touches_per_line:
            continue
        if len(upper_touches) + len(lower_touches) < cfg.min_total_touches:
            continue

        start = min(upper.start_index, lower.start_index)
        end = max(upper.end_index, lower.end_index)
        if end <= start:
            continue

        if not _converges(upper, lower):
            continue

        # the boundaries must not have crossed yet
        apex = apex_index(upper, lower)
        if apex is not None and apex <= end:
            continue

        flat_limit = cfg.flat_slope_atr_per_bar * context.size_atr
        upper_quality = _classify_slope(upper.slope_per_bar, flat_limit)
        lower_quality = _classify_slope(lower.slope_per_bar, flat_limit)

        if upper_quality == "HORIZONTAL" and lower_quality == "ASCENDING":
            pattern, direction, breakout_hint = "ASCENDING_TRIANGLE", "BULLISH", "RESISTANCE"
            breakout_level = upper.value_at(end)
        elif lower_quality == "HORIZONTAL" and upper_quality == "DESCENDING":
            pattern, direction, breakout_hint = "DESCENDING_TRIANGLE", "BEARISH", "SUPPORT"
            breakout_level = lower.value_at(end)
        elif upper_quality == "DESCENDING" and lower_quality == "ASCENDING":
            pattern, direction, breakout_hint = "SYMMETRICAL_TRIANGLE", "NEUTRAL", "BOTH"
            breakout_level = upper.value_at(end)
        else:
            continue

        width_start = width_at(upper, lower, start)
        width_end = width_at(upper, lower, end)
        min_width = size_threshold(cfg.min_width_pips, cfg.min_width_atr, context.pip_size, context.size_atr)
        if width_start < min_width:
            continue  # a sliver between two nearly identical lines is not a pattern
        contraction = 1.0 - (width_end / width_start) if width_start > 0 else 0.0
        # a "triangle" whose range never narrows is just two drifting lines
        if contraction < cfg.min_width_contraction:
            continue
        if width_end <= 0:
            continue

        evidence = [
            f"Ligne haute : {_fmt(upper.value_at(start), context.digits)} -> {_fmt(upper.value_at(end), context.digits)} "
            f"({upper.touches} touches, pente {upper.slope_per_bar / context.pip_size:.2f} pip/bougie, {upper_quality})",
            f"Ligne basse : {_fmt(lower.value_at(start), context.digits)} -> {_fmt(lower.value_at(end), context.digits)} "
            f"({lower.touches} touches, pente {lower.slope_per_bar / context.pip_size:.2f} pip/bougie, {lower_quality})",
            f"Touches totales : {upper.touches + lower.touches} (minimum {cfg.min_total_touches})",
            f"Largeur : {pips(width_start, context.pip_size):.1f} pips -> {pips(width_end, context.pip_size):.1f} pips "
            f"(contraction {contraction * 100:.1f}%)",
            f"Apex (convergence des lignes) : "
            + (f"bougie {apex} (dans {apex - end} bougies)" if apex is not None else "non atteint dans la fenetre"),
            f"Niveau de breakout surveille : {_fmt(breakout_level, context.digits)} ({breakout_hint})",
            f"Statut : triangle en cours, pas de breakout observe",
        ]

        factors = [
            ("Nombre de touches suffisant", upper.touches + lower.touches >= cfg.min_total_touches,
             params.weights.level_quality, f"{upper.touches}+{lower.touches} touches"),
            ("Chaque ligne touchee au moins deux fois",
             upper.touches >= cfg.min_touches_per_line and lower.touches >= cfg.min_touches_per_line,
             params.weights.structure_clear, f"haute {upper.touches}, basse {lower.touches}"),
            ("Convergence des lignes", _converges(upper, lower), params.weights.symmetry,
             f"pentes {upper.slope_per_bar:.6f} / {lower.slope_per_bar:.6f}"),
            ("Contraction de la figure", contraction >= cfg.min_width_contraction,
             params.weights.volume_or_time, f"largeur reduite de {contraction * 100:.1f}% "
             f"(minimum {cfg.min_width_contraction * 100:.0f}%)"),
            ("Qualite d'ajustement des lignes", min(upper.r2, lower.r2) >= 0.5, params.weights.no_conflict,
             f"R2 {upper.r2:.2f} / {lower.r2:.2f}"),
            ("Contraction mesurable", contraction > 0.1, params.weights.structure_clear,
             f"{contraction * 100:.1f}% de contraction"),
        ]
        confidence, _ = score(factors)

        pivots_used = sorted(upper_touches + lower_touches, key=lambda p: p.index)
        candidates.append(
            Candidate(
                pattern=pattern,
                direction=direction,
                pivots=pivots_used,
                evidence=evidence + [f"Confiance : {confidence}%"],
                evidence_points={
                    "pattern": pattern,
                    "upper_line": _line_points(upper, context),
                    "lower_line": _line_points(lower, context),
                    "touches_upper": [p.as_dict() for p in upper_touches],
                    "touches_lower": [p.as_dict() for p in lower_touches],
                    "apex": {"index": apex, "estimated_time_index": apex},
                    "pivots": {
                        **{f"UPPER_{i + 1}": p for i, p in enumerate(upper_touches)},
                        **{f"LOWER_{i + 1}": p for i, p in enumerate(lower_touches)},
                    },
                    "roles": {f"UPPER_{i + 1}": "H" for i in range(len(upper_touches))}
                    | {f"LOWER_{i + 1}": "L" for i in range(len(lower_touches))},
                    "measurements": {
                        "upper_touches": upper.touches,
                        "lower_touches": lower.touches,
                        "upper_slope_pips_per_bar": round(upper.slope_per_bar / context.pip_size, 3),
                        "lower_slope_pips_per_bar": round(lower.slope_per_bar / context.pip_size, 3),
                        "width_start_pips": round(pips(width_start, context.pip_size), 1),
                        "width_end_pips": round(pips(width_end, context.pip_size), 1),
                        "contraction": round(contraction, 3),
                        "apex_bars_ahead": apex - end,
                    },
                },
                factors=factors,
                parameters={**cfg.model_dump(), "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10)},
                levels={
                    "RESISTANCE": upper.value_at(end),
                    "SUPPORT": lower.value_at(end),
                },
                lines=[upper, lower],
                breakout_levels=_triangle_breakout_levels(pattern, upper, lower, end, context),
                invalidation_level=(
                    lower.value_at(end) - params.breakout.buffer_pips * context.pip_size
                    if pattern != "DESCENDING_TRIANGLE"
                    else upper.value_at(end) + params.breakout.buffer_pips * context.pip_size
                ),
                invalidation_level_type="OPPOSITE_SIDE_BROKEN",
                invalidation_reason="cloture du cote oppose avant le breakout attendu",
                detected_at_bar_time=context.candles[min(end + 1, len(context.candles) - 1)].time,
                watch_from_index=end + 1,
                max_bars_to_confirm=cfg.max_bars_to_confirm,
                notes=[f"breakout attendu {'a la hausse au-dessus de' if direction == 'BULLISH' else ('a la baisse sous' if direction == 'BEARISH' else 'dans un sens ou l autre de')} "
                       f"{_fmt(breakout_level, context.digits)}"],
            )
        )
        break  # one triangle per run is enough: it is the most recent geometry

    return candidates


def _triangle_breakout_levels(pattern: str, upper: TrendLine, lower: TrendLine, end: int, context: BarContext):
    resistance = upper.value_at(end)
    support = lower.value_at(end)
    if pattern == "ASCENDING_TRIANGLE":
        return [("RESISTANCE", resistance, "BULLISH")]
    if pattern == "DESCENDING_TRIANGLE":
        return [("SUPPORT", support, "BEARISH")]
    return [("UPPER_TRENDLINE", resistance, "BULLISH"), ("LOWER_TRENDLINE", support, "BEARISH")]


def _line_points(line: TrendLine, context: BarContext) -> dict:
    start_time = context.candles[line.start_index].time if line.start_index < len(context.candles) else 0
    end_time = context.candles[line.end_index].time if line.end_index < len(context.candles) else 0
    return {
        "from": {"time": start_time, "price": line.value_at(line.start_index)},
        "to": {"time": end_time, "price": line.value_at(line.end_index)},
        "slope_per_bar": line.slope_per_bar,
        "slope_pips_per_bar": line.slope_per_bar / context.pip_size,
        "touches": line.touches,
        "r2": round(line.r2, 4),
    }


def _converges(upper: TrendLine, lower: TrendLine) -> bool:
    return upper.slope_per_bar < lower.slope_per_bar


# ------------------------------------------------------------------- wedges
def detect_wedges(context: BarContext, params: PatternParams) -> list[Candidate]:
    """RISING WEDGE (bearish) and FALLING WEDGE (bullish)."""
    cfg = params.wedge
    tolerance = size_threshold(
        cfg.touch_tolerance_pips, cfg.touch_tolerance_atr, context.pip_size, context.size_atr
    )
    slope_min = cfg.flat_slope_atr_per_bar * context.size_atr  # same grid as _classify_slope

    candidates: list[Candidate] = []
    for high_count, low_count in ((3, 3), (3, 2), (2, 3)):
        highs = [p for p in context.pivots if p.is_high][-high_count:]
        lows = [p for p in context.pivots if not p.is_high][-low_count:]
        pair = _build_line_pair(highs, lows, tolerance)
        if pair is None:
            continue
        upper, lower, upper_touches, lower_touches = pair
        if len(upper_touches) < cfg.min_touches_per_line or len(lower_touches) < cfg.min_touches_per_line:
            continue
        if len(upper_touches) + len(lower_touches) < cfg.min_total_touches:
            continue
        if not _converges(upper, lower):
            continue

        upper_ascending = upper.slope_per_bar > slope_min
        upper_descending = upper.slope_per_bar < -slope_min
        lower_ascending = lower.slope_per_bar > slope_min
        lower_descending = lower.slope_per_bar < -slope_min

        if upper_ascending and lower_ascending:
            pattern, direction = "RISING_WEDGE", "BEARISH"
            breakout_level, breakout_type, breakout_direction = lower, "LOWER_TRENDLINE", "BEARISH"
        elif upper_descending and lower_descending:
            pattern, direction = "FALLING_WEDGE", "BULLISH"
            breakout_level, breakout_type, breakout_direction = upper, "UPPER_TRENDLINE", "BULLISH"
        else:
            continue

        start = min(upper.start_index, lower.start_index)
        end = max(upper.end_index, lower.end_index)
        apex = apex_index(upper, lower)
        if apex is not None and apex <= end:
            continue

        width_start = width_at(upper, lower, start)
        width_end = width_at(upper, lower, end)
        min_width = size_threshold(cfg.min_width_pips, cfg.min_width_atr, context.pip_size, context.size_atr)
        if width_start < min_width:
            continue  # a sliver between two nearly identical lines is not a pattern
        contraction = 1.0 - (width_end / width_start) if width_start > 0 else 0.0
        # a "triangle" whose range never narrows is just two drifting lines
        if contraction < cfg.min_width_contraction:
            continue
        if width_end <= 0:
            continue

        evidence = [
            f"Ligne haute : {_fmt(upper.value_at(start), context.digits)} -> {_fmt(upper.value_at(end), context.digits)} "
            f"(pente {upper.slope_per_bar / context.pip_size:.2f} pip/bougie)",
            f"Ligne basse : {_fmt(lower.value_at(start), context.digits)} -> {_fmt(lower.value_at(end), context.digits)} "
            f"(pente {lower.slope_per_bar / context.pip_size:.2f} pip/bougie)",
            f"Les deux lignes {'montent' if pattern == 'RISING_WEDGE' else 'descendent'} et convergent",
            f"Touches : {upper.touches} en haut / {lower.touches} en bas",
            f"Largeur : {pips(width_start, context.pip_size):.1f} -> {pips(width_end, context.pip_size):.1f} pips "
            f"(contraction {contraction * 100:.1f}%)",
            f"Breakout attendu sur la ligne {'basse' if pattern == 'RISING_WEDGE' else 'haute'} : "
            f"{_fmt(breakout_level.value_at(end), context.digits)}",
            "Statut : wedge identifie, breakout non observe",
        ]
        factors = [
            ("Convergence des deux lignes", True, params.weights.symmetry,
             f"pentes {upper.slope_per_bar:.6f} / {lower.slope_per_bar:.6f}"),
            ("Pentes significatives", min(abs(upper.slope_per_bar), abs(lower.slope_per_bar)) > slope_min,
             params.weights.structure_clear, f"seuil {slope_min:.6f}"),
            ("Touches suffisantes", upper.touches + lower.touches >= cfg.min_total_touches,
             params.weights.level_quality, f"{upper.touches}+{lower.touches}"),
            ("Contraction mesurable", contraction > 0.1, params.weights.level_quality,
             f"{contraction * 100:.1f}%"),
            ("Qualite d'ajustement", min(upper.r2, lower.r2) >= 0.5, params.weights.no_conflict,
             f"R2 {upper.r2:.2f} / {lower.r2:.2f}"),
            ("Contraction du wedge", contraction >= cfg.min_width_contraction, params.weights.volume_or_time,
             f"largeur reduite de {contraction * 100:.1f}%"),
        ]
        confidence, _ = score(factors)

        candidates.append(
            Candidate(
                pattern=pattern,
                direction=direction,
                pivots=sorted(upper_touches + lower_touches, key=lambda p: p.index),
                evidence=evidence + [f"Confiance : {confidence}%"],
                evidence_points={
                    "pattern": pattern,
                    "upper_line": _line_points(upper, context),
                    "lower_line": _line_points(lower, context),
                    "touches_upper": [p.as_dict() for p in upper_touches],
                    "touches_lower": [p.as_dict() for p in lower_touches],
                    "pivots": {
                        **{f"UPPER_{i + 1}": p for i, p in enumerate(upper_touches)},
                        **{f"LOWER_{i + 1}": p for i, p in enumerate(lower_touches)},
                    },
                    "roles": {f"UPPER_{i + 1}": "H" for i in range(len(upper_touches))}
                    | {f"LOWER_{i + 1}": "L" for i in range(len(lower_touches))},
                    "measurements": {
                        "upper_slope_pips_per_bar": round(upper.slope_per_bar / context.pip_size, 3),
                        "lower_slope_pips_per_bar": round(lower.slope_per_bar / context.pip_size, 3),
                        "contraction": round(contraction, 3),
                        "apex_bars_ahead": apex - end,
                    },
                },
                factors=factors,
                parameters={**cfg.model_dump(), "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10)},
                levels={
                    "UPPER_TRENDLINE": upper.value_at(end),
                    "LOWER_TRENDLINE": lower.value_at(end),
                },
                lines=[upper, lower],
                breakout_levels=[(breakout_type, breakout_level.value_at(end), breakout_direction)],
                invalidation_level=(
                    upper.value_at(end) + params.breakout.buffer_pips * context.pip_size
                    if pattern == "RISING_WEDGE"
                    else lower.value_at(end) - params.breakout.buffer_pips * context.pip_size
                ),
                invalidation_level_type="OPPOSITE_SIDE_BROKEN",
                invalidation_reason="cloture du cote oppose avant le breakout attendu",
                detected_at_bar_time=context.candles[min(end + 1, len(context.candles) - 1)].time,
                watch_from_index=end + 1,
                max_bars_to_confirm=cfg.max_bars_to_confirm,
                notes=[
                    f"breakout attendu {'sous' if direction == 'BEARISH' else 'au-dessus'} de "
                    f"{_fmt(breakout_level.value_at(end), context.digits)}"
                ],
            )
        )
        break

    return candidates


# ----------------------------------------------------------------- channels
def detect_channels(context: BarContext, params: PatternParams) -> list[Candidate]:
    """Two near-parallel lines with several real touches."""
    cfg = params.channel
    tolerance = size_threshold(
        cfg.touch_tolerance_pips, cfg.touch_tolerance_atr, context.pip_size, context.size_atr
    )
    slope_min = cfg.flat_slope_atr_per_bar * context.size_atr  # same grid as _classify_slope

    candidates: list[Candidate] = []
    for count in (3, 2):
        highs = [p for p in context.pivots if p.is_high][-count:]
        lows = [p for p in context.pivots if not p.is_high][-count:]
        pair = _build_line_pair(highs, lows, tolerance)
        if pair is None:
            continue
        upper, lower, upper_touches, lower_touches = pair
        if len(upper_touches) < cfg.min_touches_per_line or len(lower_touches) < cfg.min_touches_per_line:
            continue
        if len(upper_touches) + len(lower_touches) < cfg.min_total_touches:
            continue
        if _converges(upper, lower):
            continue  # converging = triangle, not a channel

        if max(abs(upper.slope_per_bar), abs(lower.slope_per_bar)) < slope_min:
            continue  # a flat parallel channel is a rectangle

        gap = relative_slope_gap(upper, lower, context.size_atr)
        if gap > cfg.parallel_tolerance:
            continue

        start = min(upper.start_index, lower.start_index)
        end = max(upper.end_index, lower.end_index)
        width_start = width_at(upper, lower, start)
        width_end = width_at(upper, lower, end)
        width_drift = abs(width_end - width_start) / width_start if width_start > 0 else 1.0
        if width_drift > cfg.max_width_drift:
            continue
        if width_start < cfg.min_width_atr * context.size_atr:
            continue

        ascending = upper.slope_per_bar > 0
        direction = "BULLISH" if ascending else "BEARISH"

        evidence = [
            f"Ligne haute : {_fmt(upper.value_at(start), context.digits)} -> {_fmt(upper.value_at(end), context.digits)} "
            f"({upper.touches} touches)",
            f"Ligne basse : {_fmt(lower.value_at(start), context.digits)} -> {_fmt(lower.value_at(end), context.digits)} "
            f"({lower.touches} touches)",
            f"Pentes : {upper.slope_per_bar / context.pip_size:.2f} et {lower.slope_per_bar / context.pip_size:.2f} pip/bougie "
            f"(ecart relatif {gap:.3f}, tolerance {cfg.parallel_tolerance})",
            f"Largeur : {pips(width_start, context.pip_size):.1f} -> {pips(width_end, context.pip_size):.1f} pips "
            f"(derive {width_drift * 100:.1f}%)",
            f"Canal {'ascendant' if ascending else 'descendant'}",
            "Statut : canal en cours",
        ]
        factors = [
            ("Parallellisme", gap <= cfg.parallel_tolerance, params.weights.structure_clear, f"ecart {gap:.3f}"),
            ("Touches suffisantes", upper.touches + lower.touches >= cfg.min_total_touches,
             params.weights.level_quality, f"{upper.touches}+{lower.touches}"),
            ("Largeur stable", width_drift <= cfg.max_width_drift, params.weights.symmetry,
             f"derive {width_drift * 100:.1f}%"),
            ("Largeur exploitable", width_start >= cfg.min_width_atr * context.size_atr, params.weights.volume_or_time,
             f"{pips(width_start, context.pip_size):.1f} pips"),
            ("Qualite d'ajustement", min(upper.r2, lower.r2) >= 0.5, params.weights.no_conflict,
             f"R2 {upper.r2:.2f} / {lower.r2:.2f}"),
            ("Pente directionnelle", True, params.weights.structure_clear,
             f"{upper.slope_per_bar / context.pip_size:.2f} pip/bougie"),
        ]
        confidence, _ = score(factors)

        candidates.append(
            Candidate(
                pattern="CHANNEL",
                direction=direction,
                pivots=sorted(upper_touches + lower_touches, key=lambda p: p.index),
                evidence=evidence + [f"Confiance : {confidence}%"],
                evidence_points={
                    "pattern": "CHANNEL",
                    "upper_line": _line_points(upper, context),
                    "lower_line": _line_points(lower, context),
                    "touches_upper": [p.as_dict() for p in upper_touches],
                    "touches_lower": [p.as_dict() for p in lower_touches],
                    "pivots": {
                        **{f"UPPER_{i + 1}": p for i, p in enumerate(upper_touches)},
                        **{f"LOWER_{i + 1}": p for i, p in enumerate(lower_touches)},
                    },
                    "roles": {f"UPPER_{i + 1}": "H" for i in range(len(upper_touches))}
                    | {f"LOWER_{i + 1}": "L" for i in range(len(lower_touches))},
                    "measurements": {
                        "slope_pips_per_bar_upper": round(upper.slope_per_bar / context.pip_size, 3),
                        "slope_pips_per_bar_lower": round(lower.slope_per_bar / context.pip_size, 3),
                        "slope_gap_relative": round(gap, 4),
                        "upper_touches": upper.touches,
                        "lower_touches": lower.touches,
                        "width_start_pips": round(pips(width_start, context.pip_size), 1),
                        "width_end_pips": round(pips(width_end, context.pip_size), 1),
                    },
                },
                factors=factors,
                parameters={**cfg.model_dump(), "atr": round(context.atr, 10),
                "atr_slow": round(context.atr_slow, 10)},
                levels={
                    "CHANNEL_UPPER": upper.value_at(end),
                    "CHANNEL_LOWER": lower.value_at(end),
                },
                lines=[upper, lower],
                breakout_levels=[
                    ("CHANNEL_UPPER", upper.value_at(end), "BULLISH" if ascending else "BEARISH"),
                    ("CHANNEL_LOWER", lower.value_at(end), "BEARISH" if ascending else "BULLISH"),
                ],
                detected_at_bar_time=context.candles[min(end + 1, len(context.candles) - 1)].time,
                watch_from_index=end + 1,
                max_bars_to_confirm=None,
            )
        )
        break

    return candidates
