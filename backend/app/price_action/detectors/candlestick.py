"""Candlestick detectors: engulfing, pin bar, hammer/shooting star, inside/outside
bar, doji.

Each function receives a :class:`ScanContext` (measured candles + centralised
parameters + one volatility scale) and returns candidates with:

* the **criteria** it checked (name, passed, weight, human-readable detail) - the
  confidence is exactly their weighted share, so nothing is guessed;
* the **measurements** (body size, wicks, ratios in pips and in % of range) that a
  human can re-check on the real candle;
* the **trigger / invalidation levels** used by the lifecycle (a later close
  beyond the trigger confirms, a close beyond the other side invalidates).
"""

from __future__ import annotations

from app.patterns.models import Candidate
from app.price_action.candles import CandleMetrics, ge, gt, le, lt, pips
from app.price_action.models import ScanContext

#: anti-flood cap per pattern and per run, same idea as the chartist engine
MAX_PER_PATTERN = 2


def _metrics(metrics: list[CandleMetrics], index: int) -> CandleMetrics | None:
    if index < 0 or index >= len(metrics):
        return None
    return metrics[index]


def _as_marker(metric: CandleMetrics, role: str, is_high: bool) -> dict[str, object]:
    """Marker view of a candle, consumed by the shared drawing builder."""
    return {
        "index": metric.index,
        "time": metric.time,
        "price": metric.high if is_high else metric.low,
        "type": "HIGH" if is_high else "LOW",
        "is_high": is_high,
        "kind": "HIGH" if is_high else "LOW",
        "role": role,
    }


def _p(metric: CandleMetrics, pip_size: float, value: float) -> float:
    return pips(value, pip_size)


# --------------------------------------------------------------------- engulfing
def _engulfing(ctx: ScanContext, index: int, *, bullish: bool) -> Candidate | None:
    cfg = ctx.params.engulfing
    pip_size = ctx.pip_size
    previous = _metrics(ctx.metrics, index - 1)
    current = _metrics(ctx.metrics, index)
    if previous is None or current is None:
        return None

    pattern = "BULLISH_ENGULFING" if bullish else "BEARISH_ENGULFING"
    direction = "BULLISH" if bullish else "BEARISH"

    # --- deterministic gates: no candidate exists unless every rule holds
    if cfg.require_direction_change and not (previous.bearish if bullish else previous.bullish):
        return None
    if not (current.bullish if bullish else current.bearish):
        return None

    min_previous_body = ctx.min_size(cfg.min_previous_body_pips, cfg.min_previous_body_atr)
    if lt(previous.body_size, min_previous_body) or previous.body_size <= 0:
        return None

    # body containment: how much of the previous real body the current one covers
    overlap = min(current.body_top, previous.body_top) - max(current.body_bottom, previous.body_bottom)
    coverage = overlap / previous.body_size
    ratio = current.body_size / previous.body_size
    opposite_wick_ratio = current.upper_wick_ratio if bullish else current.lower_wick_ratio

    if lt(coverage, cfg.min_coverage):
        return None
    if lt(ratio, cfg.min_body_multiple):
        return None
    if lt(current.body_ratio, cfg.min_body_ratio):
        return None
    if gt(opposite_wick_ratio, cfg.max_opposite_wick_ratio):
        return None
    if lt(current.range, ctx.min_size(cfg.min_candle_range_pips, cfg.min_candle_range_atr)):
        return None

    trigger = current.high if bullish else current.low
    invalidation = current.low if bullish else current.high
    factors = [
        (
            "Bougie precedente dans le sens oppose",
            True,
            ctx.params.weights.candle_geometry,
            f"bougie {index - 1} {'baissiere' if bullish else 'haussiere'} "
            f"({_p(previous, pip_size, previous.body_size):.1f} pips de corps)",
        ),
        (
            "Bougie actuelle dans le sens du motif",
            True,
            ctx.params.weights.candle_geometry,
            f"bougie {index} {'haussiere' if bullish else 'baissiere'} "
            f"({_p(current, pip_size, current.body_size):.1f} pips de corps)",
        ),
        (
            "Englobement du corps precedent",
            coverage >= cfg.min_coverage * 1.5,
            ctx.params.weights.relative_size,
            f"couverture {coverage * 100:.0f}% (minimum {cfg.min_coverage * 100:.0f}%)",
        ),
        (
            "Corps au moins aussi grand",
            ratio >= cfg.min_body_multiple * 1.5,
            ctx.params.weights.relative_size,
            f"x{ratio:.2f} (minimum x{cfg.min_body_multiple:.2f})",
        ),
        (
            "Meche opposee contenue",
            opposite_wick_ratio <= cfg.max_opposite_wick_ratio * 0.5,
            ctx.params.weights.candle_geometry,
            f"{opposite_wick_ratio * 100:.0f}% du range (maximum {cfg.max_opposite_wick_ratio * 100:.0f}%)",
        ),
        (
            "Corps majoritaire dans la bougie",
            current.body_ratio >= cfg.min_body_ratio * 1.3,
            ctx.params.weights.candle_geometry,
            f"corps/range {current.body_ratio * 100:.0f}%",
        ),
    ]
    evidence = [
        f"Bougie {index - 1} : O {previous.open} H {previous.high} L {previous.low} C {previous.close}",
        f"Bougie {index} : O {current.open} H {current.high} L {current.low} C {current.close}",
        f"Englobement du corps reel : {coverage * 100:.0f}% du corps precedent couvert",
        f"Taille des corps : {_p(current, pip_size, current.body_size):.1f} pips contre "
        f"{_p(previous, pip_size, previous.body_size):.1f} pips (x{ratio:.2f})",
        f"Niveau de confirmation : cloture {'au-dessus' if bullish else 'en dessous'} de {trigger:.{ctx.digits}f}",
    ]

    return Candidate(
        pattern=pattern,
        direction=direction,
        pivots=[],
        evidence=evidence,
        evidence_points={
            "pattern": pattern,
            "pattern_kind": "CANDLESTICK",
            "previous_candle": previous.as_dict(),
            "current_candle": current.as_dict(),
            "body_ratio": round(current.body_ratio, 4),
            "coverage_ratio": round(coverage, 4),
            "measurements": {
                "coverage_ratio": round(coverage, 4),
                "min_coverage": cfg.min_coverage,
                "body_multiple": round(ratio, 4),
                "min_body_multiple": cfg.min_body_multiple,
                "body_ratio": round(current.body_ratio, 4),
                "opposite_wick_ratio": round(opposite_wick_ratio, 4),
                "range_pips": round(_p(current, pip_size, current.range), 1),
                "trigger": trigger,
                "atr": round(ctx.atr, 6),
            },
            "pivots": {
                "PREVIOUS": _as_marker(previous, "PRECEDENTE", not bullish),
                "PATTERN": _as_marker(current, "MOTIF", bullish),
            },
            "roles": {"PREVIOUS": "B1", "PATTERN": "B2"},
        },
        factors=factors,
        parameters=cfg.model_dump(),
        levels={
            "TRIGGER": trigger,
            "INVALIDATION": invalidation,
            "PATTERN_HIGH": current.high,
            "PATTERN_LOW": current.low,
        },
        zones=[
            {
                "time_start": previous.time,
                "time_end": current.time,
                "price_top": max(previous.high, current.high),
                "price_bottom": min(previous.low, current.low),
                "label": "ENGLOBEMENT",
                "kind": "PATTERN",
            }
        ],
        breakout_levels=[("PATTERN_HIGH" if bullish else "PATTERN_LOW", trigger, direction)],
        invalidation_level=invalidation,
        invalidation_level_type="PATTERN_LOW" if bullish else "PATTERN_HIGH",
        invalidation_reason=(
            f"cloture {'sous le plus bas' if bullish else 'au-dessus du plus haut'} de la bougie de motif"
        ),
        detected_at_bar_time=current.time,
        watch_from_index=index,
        max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
    )


def _scan_candles(ctx: ScanContext, build) -> list[Candidate]:
    """Run one detector on the most recent ``scan_bars`` closed candles (newest first).

    A candlestick pattern older than the scan window is history; and finding the
    same shape ten times in a row would be exactly the over-detection the brief
    forbids, hence ``MAX_PER_PATTERN``.
    """
    metrics = ctx.metrics
    if not metrics:
        return []
    window = ctx.params.globals.scan_bars
    start = max(1, len(metrics) - window)  # index 0 has no previous candle
    found: list[Candidate] = []
    for index in range(len(metrics) - 1, start - 1, -1):
        candidate = build(index)
        if candidate is not None:
            found.append(candidate)
            if len(found) >= MAX_PER_PATTERN:
                break
    return found


def detect_bullish_engulfing(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(ctx, lambda index: _engulfing(ctx, index, bullish=True))


def detect_bearish_engulfing(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(ctx, lambda index: _engulfing(ctx, index, bullish=False))


# ------------------------------------------------------------------------ pin bar
def _pin(ctx: ScanContext, index: int, *, bearish: bool, cfg, pattern: str) -> Candidate | None:
    """Pin bar geometry, shared by pin bars and by hammer / shooting star.

    Never "a long wick": the definition is a conjunction of measurable ratios -
    dominant wick / range, dominant wick / body, opposite wick / range, body /
    range, body position inside the range, and a minimum range vs volatility.
    """
    candle = _metrics(ctx.metrics, index)
    if candle is None or candle.range <= 0:
        return None
    pip_size = ctx.pip_size

    if lt(candle.range, ctx.min_size(cfg.min_range_pips, cfg.min_range_atr)):
        return None
    if gt(candle.body_ratio, cfg.max_body_ratio):
        return None

    dominant = candle.upper_wick if bearish else candle.lower_wick
    opposite = candle.lower_wick if bearish else candle.upper_wick
    dominant_ratio = candle.upper_wick_ratio if bearish else candle.lower_wick_ratio
    opposite_ratio = opposite / candle.range

    if lt(dominant_ratio, cfg.min_wick_range_ratio):
        return None
    if gt(opposite_ratio, cfg.max_opposite_wick_ratio):
        return None
    if candle.body_size > 0:
        if lt(dominant / candle.body_size, cfg.min_wick_body_ratio):
            return None
    elif dominant <= 0:
        return None

    # body position: a bullish pin must have its body in the upper part of the range
    position = (candle.close_position + (candle.body_top - candle.low) / candle.range) / 2
    if not bearish and lt(position, cfg.body_position_min):
        return None
    if bearish and lt(1.0 - position, cfg.body_position_min):
        return None

    direction = "BEARISH" if bearish else "BULLISH"
    trigger = candle.high if bearish else candle.low
    wick_to_body = candle.wick_to_body
    factors = [
        (
            "Meche dominante suffisante",
            dominant_ratio >= cfg.min_wick_range_ratio * 1.15,
            ctx.params.weights.candle_geometry,
            f"{dominant_ratio * 100:.0f}% du range (minimum {cfg.min_wick_range_ratio * 100:.0f}%)",
        ),
        (
            "Rapport meche dominante / corps",
            candle.body_size > 0 and dominant / candle.body_size >= cfg.min_wick_body_ratio * 1.25,
            ctx.params.weights.candle_geometry,
            f"x{wick_to_body:.2f} (minimum x{cfg.min_wick_body_ratio:.2f})"
            if wick_to_body != float("inf")
            else "corps nul : rapport infini",
        ),
        (
            "Meche opposee negligeable",
            opposite_ratio <= cfg.max_opposite_wick_ratio * 0.6,
            ctx.params.weights.candle_geometry,
            f"{opposite_ratio * 100:.0f}% du range (maximum {cfg.max_opposite_wick_ratio * 100:.0f}%)",
        ),
        (
            "Petit corps dans la bougie",
            candle.body_ratio <= cfg.max_body_ratio * 0.75,
            ctx.params.weights.candle_geometry,
            f"corps/range {candle.body_ratio * 100:.0f}% (maximum {cfg.max_body_ratio * 100:.0f}%)",
        ),
        (
            "Corps positionne du bon cote",
            position >= cfg.body_position_min * 1.05,
            ctx.params.weights.relative_size,
            f"corps a {position * 100:.0f}% du range (minimum {cfg.body_position_min * 100:.0f}%)",
        ),
    ]
    evidence = [
        f"Bougie {index} : O {candle.open} H {candle.high} L {candle.low} C {candle.close}",
        f"Meche {'haute' if bearish else 'basse'} : {_p(candle, pip_size, dominant):.1f} pips "
        f"= {dominant_ratio * 100:.0f}% du range ({_p(candle, pip_size, candle.range):.1f} pips)",
        f"Corps : {_p(candle, pip_size, candle.body_size):.1f} pips = {candle.body_ratio * 100:.0f}% du range, "
        f"rapport meche/corps x{wick_to_body:.2f}",
        f"Meche opposee : {_p(candle, pip_size, opposite):.1f} pips = {opposite_ratio * 100:.0f}% du range",
        f"Position du corps : {position * 100:.0f}% du range depuis le bas",
        f"Niveau de confirmation : cloture {'au-dessus' if bearish else 'en dessous'} de {trigger:.{ctx.digits}f}",
    ]

    return Candidate(
        pattern=pattern,
        direction=direction,
        pivots=[],
        evidence=evidence,
        evidence_points={
            "pattern": pattern,
            "pattern_kind": "CANDLESTICK",
            "current_candle": candle.as_dict(),
            "body_ratio": round(candle.body_ratio, 4),
            "wick_ratios": candle.as_dict()["wick_ratios"],
            "measurements": {
                "dominant_side": "UPPER" if bearish else "LOWER",
                "dominant_wick_pips": round(_p(candle, pip_size, dominant), 1),
                "dominant_wick_ratio": round(dominant_ratio, 4),
                "opposite_wick_ratio": round(opposite_ratio, 4),
                "wick_to_body": round(wick_to_body, 2) if wick_to_body != float("inf") else None,
                "body_ratio": round(candle.body_ratio, 4),
                "body_position": round(position, 4),
                "range_pips": round(_p(candle, pip_size, candle.range), 1),
                "trigger": trigger,
                "atr": round(ctx.atr, 6),
            },
            "pivots": {"PATTERN": _as_marker(candle, "MOTIF", bearish)},
            "roles": {"PATTERN": "PB"},
        },
        factors=factors,
        parameters=cfg.model_dump(),
        levels={
            "TRIGGER": trigger,
            "INVALIDATION": candle.low if bearish else candle.high,
            "PATTERN_HIGH": candle.high,
            "PATTERN_LOW": candle.low,
        },
        zones=[
            {
                "time_start": candle.time,
                "time_end": candle.time,
                "price_top": candle.high,
                "price_bottom": candle.low,
                "label": pattern,
                "kind": "PATTERN",
            }
        ],
        breakout_levels=[("PATTERN_HIGH" if bearish else "PATTERN_LOW", trigger, direction)],
        invalidation_level=candle.low if bearish else candle.high,
        invalidation_level_type="PATTERN_LOW" if bearish else "PATTERN_HIGH",
        invalidation_reason=(
            "cloture sous le plus bas de la bougie de motif"
            if bearish
            else "cloture au-dessus du plus haut de la bougie de motif"
        ),
        detected_at_bar_time=candle.time,
        watch_from_index=index,
        max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
    )


def detect_bullish_pin_bar(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(
        ctx, lambda index: _pin(ctx, index, bearish=False, cfg=ctx.params.pin_bar, pattern="BULLISH_PIN_BAR")
    )


def detect_bearish_pin_bar(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(
        ctx, lambda index: _pin(ctx, index, bearish=True, cfg=ctx.params.pin_bar, pattern="BEARISH_PIN_BAR")
    )


# -------------------------------------------------------- hammer / shooting star
def _hammer(ctx: ScanContext, index: int, *, bearish: bool) -> Candidate | None:
    cfg = ctx.params.hammer
    pattern = "SHOOTING_STAR" if bearish else "HAMMER"
    candidate = _pin(ctx, index, bearish=bearish, cfg=cfg, pattern=pattern)
    if candidate is None:
        return None

    # A hammer is a pin bar **after a move**: without the prior move it is only a
    # pin bar, and calling it a hammer would be an interpretation.
    #
    # Measured on the ``context_lookback_bars`` bars before the pattern:
    #   * amplitude = max(high) - min(low)  (the swing that just happened);
    #   * direction = the last close of the window sits in the half of the swing
    #     we expect (lower half for a hammer, upper half for a shooting star).
    pip_size = ctx.pip_size
    window = ctx.metrics[max(0, index - cfg.context_lookback_bars) : index]
    if not window:
        return None
    swing_high = max(m.high for m in window)
    swing_low = min(m.low for m in window)
    swing = swing_high - swing_low
    reference_close = window[-1].close
    min_move = ctx.min_size(cfg.context_min_move_pips, cfg.context_min_move_atr)
    if lt(swing, min_move):
        return None
    position = (reference_close - swing_low) / swing if swing > 0 else 0.5
    if not bearish and position > 0.5:
        return None  # a hammer needs price to have come *down* into the low
    if bearish and position < 0.5:
        return None

    candidate.factors.append(
        (
            f"Mouvement prealable ({'avance' if bearish else 'repli'})",
            swing >= min_move * 1.4,
            ctx.params.weights.relative_size,
            f"amplitude {pips(swing, pip_size):.1f} pips sur {len(window)} bougies "
            f"(minimum {pips(min_move, pip_size):.1f})",
        )
    )
    candidate.factors.append(
        (
            "Prix arrive dans la zone du mouvement",
            position <= 0.35 if not bearish else position >= 0.65,
            ctx.params.weights.structure_clear,
            f"cloture a {position * 100:.0f}% du mouvement "
            f"({'moitie basse' if not bearish else 'moitie haute'} exigee)",
        )
    )
    candidate.evidence.append(
        f"Contexte : {'avance' if bearish else 'repli'} de {pips(swing, pip_size):.1f} pips sur les "
        f"{len(window)} bougies precedentes (sans ce mouvement, ce n'est qu'un pin bar)"
    )
    measurements = candidate.evidence_points["measurements"]  # type: ignore[index]
    measurements["prior_move_pips"] = round(pips(swing, pip_size), 1)  # type: ignore[index]
    measurements["required_prior_move_pips"] = round(pips(min_move, pip_size), 1)  # type: ignore[index]
    candidate.evidence_points["context"] = {
        "prior_swing_pips": round(pips(swing, pip_size), 1),
        "prior_move_bars": len(window),
        "required_pips": round(pips(min_move, pip_size), 1),
        "close_position_in_swing": round(position, 3),
    }
    return candidate


def detect_hammer(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(ctx, lambda index: _hammer(ctx, index, bearish=False))


def detect_shooting_star(ctx: ScanContext) -> list[Candidate]:
    return _scan_candles(ctx, lambda index: _hammer(ctx, index, bearish=True))


# -------------------------------------------------------------- inside / outside
def detect_inside_bar(ctx: ScanContext) -> list[Candidate]:
    cfg = ctx.params.inside_bar
    pip_size = ctx.pip_size

    def build(index: int) -> Candidate | None:
        mother = _metrics(ctx.metrics, index - 1)
        inside = _metrics(ctx.metrics, index)
        if mother is None or inside is None or mother.range <= 0:
            return None
        min_mother = ctx.min_size(cfg.min_mother_range_pips, cfg.min_mother_range_atr)
        if lt(mother.range, min_mother):
            return None
        tolerance = cfg.containment_tolerance_pips * pip_size
        upper_breach = inside.high - mother.high
        lower_breach = mother.low - inside.low
        if gt(upper_breach, tolerance) or gt(lower_breach, tolerance):
            return None
        ratio = inside.range / mother.range
        if gt(ratio, cfg.max_range_ratio):
            return None

        return Candidate(
            pattern="INSIDE_BAR",
            direction="NEUTRAL",
            pivots=[],
            evidence=[
                f"Bougie mere {index - 1} : range {pips(mother.range, pip_size):.1f} pips "
                f"({mother.low} - {mother.high})",
                f"Bougie interne {index} : range {pips(inside.range, pip_size):.1f} pips "
                f"({inside.low} - {inside.high})",
                f"Le range interne represente {ratio * 100:.0f}% du range de la mere",
                "Niveau surveille : sortie du range de la bougie mere, dans un sens ou dans l'autre",
            ],
            evidence_points={
                "pattern": "INSIDE_BAR",
                "pattern_kind": "CANDLESTICK",
                "mother_candle": mother.as_dict(),
                "inside_candle": inside.as_dict(),
                "range_ratio": round(ratio, 4),
                "measurements": {
                    "range_ratio": round(ratio, 4),
                    "mother_range_pips": round(pips(mother.range, pip_size), 1),
                    "inside_range_pips": round(pips(inside.range, pip_size), 1),
                    "upper_breach_pips": round(pips(upper_breach, pip_size), 2),
                    "lower_breach_pips": round(pips(lower_breach, pip_size), 2),
                    "tolerance_pips": cfg.containment_tolerance_pips,
                    "atr": round(ctx.atr, 6),
                },
                "pivots": {
                    "MOTHER": _as_marker(mother, "MERE", True),
                    "INSIDE": _as_marker(inside, "INTERNE", False),
                },
                "roles": {"MOTHER": "MB", "INSIDE": "IB"},
            },
            factors=[
                (
                    "Range contenu dans la bougie mere",
                    True,
                    ctx.params.weights.candle_geometry,
                    f"depassement haut {pips(upper_breach, pip_size):+.2f} pip / bas "
                    f"{pips(lower_breach, pip_size):+.2f} pip (tolerance "
                    f"{cfg.containment_tolerance_pips} pip)",
                ),
                (
                    "Compression du range",
                    ratio <= cfg.max_range_ratio * 0.7,
                    ctx.params.weights.relative_size,
                    f"ratio {ratio * 100:.0f}% (maximum {cfg.max_range_ratio * 100:.0f}%)",
                ),
                (
                    "Bougie mere significative",
                    mother.range >= min_mother * 1.4,
                    ctx.params.weights.relative_size,
                    f"{pips(mother.range, pip_size):.1f} pips (minimum {pips(min_mother, pip_size):.1f})",
                ),
            ],
            parameters=cfg.model_dump(),
            levels={
                "MOTHER_HIGH": mother.high,
                "MOTHER_LOW": mother.low,
                "INSIDE_HIGH": inside.high,
                "INSIDE_LOW": inside.low,
            },
            zones=[
                {
                    "time_start": mother.time,
                    "time_end": inside.time,
                    "price_top": mother.high,
                    "price_bottom": mother.low,
                    "label": "INSIDE BAR",
                    "kind": "PATTERN",
                }
            ],
            # both sides are watched: the direction is only known at the break
            breakout_levels=[
                ("MOTHER_HIGH", mother.high, "BULLISH"),
                ("MOTHER_LOW", mother.low, "BEARISH"),
            ],
            invalidation_level=None,
            detected_at_bar_time=inside.time,
            watch_from_index=index,
            max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
        )

    return _scan_candles(ctx, build)


def detect_outside_bar(ctx: ScanContext) -> list[Candidate]:
    cfg = ctx.params.outside_bar
    pip_size = ctx.pip_size

    def build(index: int) -> Candidate | None:
        previous = _metrics(ctx.metrics, index - 1)
        current = _metrics(ctx.metrics, index)
        if previous is None or current is None or previous.range <= 0:
            return None
        min_range = ctx.min_size(cfg.min_range_pips, cfg.min_range_atr)
        if lt(current.range, min_range):
            return None
        breach = cfg.min_breach_pips * pip_size
        # both sides must be exceeded by *at least* min_breach_pips (inclusive)
        if not ge(current.high, previous.high + breach) or not le(current.low, previous.low - breach):
            return None
        ratio = current.range / previous.range
        if lt(ratio, cfg.min_range_ratio):
            return None
        direction = "BULLISH" if current.bullish else ("BEARISH" if current.bearish else "NEUTRAL")
        upper_breach = current.high - previous.high
        lower_breach = previous.low - current.low

        return Candidate(
            pattern="OUTSIDE_BAR",
            direction=direction,
            pivots=[],
            evidence=[
                f"Bougie precedente {index - 1} : H {previous.high} / L {previous.low} "
                f"({pips(previous.range, pip_size):.1f} pips)",
                f"Bougie d'expansion {index} : H {current.high} / L {current.low} "
                f"({pips(current.range, pip_size):.1f} pips)",
                f"Range multiplie par x{ratio:.2f} ; haut depasse de {pips(upper_breach, pip_size):+.1f} pip "
                f"et bas de {pips(lower_breach, pip_size):+.1f} pip",
                "Absorption : toute la bougie precedente est contenue dans la nouvelle",
            ],
            evidence_points={
                "pattern": "OUTSIDE_BAR",
                "pattern_kind": "CANDLESTICK",
                "previous_candle": previous.as_dict(),
                "current_candle": current.as_dict(),
                "previous_high": previous.high,
                "previous_low": previous.low,
                "current_high": current.high,
                "current_low": current.low,
                "range_ratio": round(ratio, 4),
                "measurements": {
                    "range_ratio": round(ratio, 4),
                    "previous_range_pips": round(pips(previous.range, pip_size), 1),
                    "current_range_pips": round(pips(current.range, pip_size), 1),
                    "upper_breach_pips": round(pips(upper_breach, pip_size), 2),
                    "lower_breach_pips": round(pips(lower_breach, pip_size), 2),
                    "atr": round(ctx.atr, 6),
                },
                "pivots": {
                    "PREVIOUS": _as_marker(previous, "PRECEDENTE", True),
                    "OUTSIDE": _as_marker(current, "EXPANSION", False),
                },
                "roles": {"PREVIOUS": "B1", "OUTSIDE": "OB"},
            },
            factors=[
                (
                    "Expansion haute et basse",
                    True,
                    ctx.params.weights.candle_geometry,
                    f"haut {pips(upper_breach, pip_size):+.1f} pip / bas {pips(lower_breach, pip_size):+.1f} pip",
                ),
                (
                    "Expansion du range",
                    ratio >= cfg.min_range_ratio * 1.3,
                    ctx.params.weights.relative_size,
                    f"x{ratio:.2f} (minimum x{cfg.min_range_ratio:.2f})",
                ),
                (
                    "Bougie significative",
                    current.range >= min_range * 1.4,
                    ctx.params.weights.relative_size,
                    f"{pips(current.range, pip_size):.1f} pips (minimum {pips(min_range, pip_size):.1f})",
                ),
                (
                    "Direction lisible",
                    direction != "NEUTRAL",
                    ctx.params.weights.candle_geometry,
                    f"cloture {'haussiere' if direction == 'BULLISH' else 'baissiere' if direction == 'BEARISH' else 'neutre'}",
                ),
            ],
            parameters=cfg.model_dump(),
            levels={
                "PREVIOUS_HIGH": previous.high,
                "PREVIOUS_LOW": previous.low,
                "PATTERN_HIGH": current.high,
                "PATTERN_LOW": current.low,
            },
            zones=[
                {
                    "time_start": previous.time,
                    "time_end": current.time,
                    "price_top": current.high,
                    "price_bottom": current.low,
                    "label": "OUTSIDE BAR",
                    "kind": "PATTERN",
                }
            ],
            breakout_levels=[
                ("PATTERN_HIGH", current.high, "BULLISH"),
                ("PATTERN_LOW", current.low, "BEARISH"),
            ],
            detected_at_bar_time=current.time,
            watch_from_index=index,
            max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
        )

    return _scan_candles(ctx, build)


# --------------------------------------------------------------------------- doji
def detect_doji(ctx: ScanContext) -> list[Candidate]:
    cfg = ctx.params.doji
    pip_size = ctx.pip_size

    def build(index: int) -> Candidate | None:
        candle = _metrics(ctx.metrics, index)
        if candle is None or candle.range <= 0:
            return None
        min_range = ctx.min_size(cfg.min_range_pips, cfg.min_range_atr)
        if lt(candle.range, min_range):
            return None
        ratio = candle.body_ratio
        if gt(ratio, cfg.max_body_ratio):
            return None
        long_legged = (
            ge(candle.upper_wick_ratio, cfg.long_legged_wick_ratio)
            and ge(candle.lower_wick_ratio, cfg.long_legged_wick_ratio)
        )

        return Candidate(
            pattern="DOJI",
            direction="NEUTRAL",
            pivots=[],
            evidence=[
                f"Bougie {index} : O {candle.open} H {candle.high} L {candle.low} C {candle.close}",
                f"Corps reel : {pips(candle.body_size, pip_size):.2f} pips pour un range de "
                f"{pips(candle.range, pip_size):.1f} pips (corps/range {ratio * 100:.1f}%)",
                f"Meches : haute {pips(candle.upper_wick, pip_size):.1f} pips / basse "
                f"{pips(candle.lower_wick, pip_size):.1f} pips",
                "Indecision : la bougie se cloture au niveau de son ouverture, sans conclusion",
            ],
            evidence_points={
                "pattern": "DOJI",
                "pattern_kind": "CANDLESTICK",
                "current_candle": candle.as_dict(),
                "body_ratio": round(ratio, 4),
                "long_legged": long_legged,
                "measurements": {
                    "body_ratio": round(ratio, 4),
                    "max_body_ratio": cfg.max_body_ratio,
                    "range_pips": round(pips(candle.range, pip_size), 1),
                    "upper_wick_pips": round(pips(candle.upper_wick, pip_size), 1),
                    "lower_wick_pips": round(pips(candle.lower_wick, pip_size), 1),
                    "long_legged": long_legged,
                    "atr": round(ctx.atr, 6),
                },
                "pivots": {"PATTERN": _as_marker(candle, "MOTIF", True)},
                "roles": {"PATTERN": "DOJI"},
            },
            factors=[
                (
                    "Corps quasi nul",
                    ratio <= cfg.max_body_ratio * 0.6,
                    ctx.params.weights.candle_geometry,
                    f"corps/range {ratio * 100:.1f}% (maximum {cfg.max_body_ratio * 100:.0f}%)",
                ),
                (
                    "Range significatif",
                    candle.range >= min_range * 1.4,
                    ctx.params.weights.relative_size,
                    f"{pips(candle.range, pip_size):.1f} pips (minimum {pips(min_range, pip_size):.1f})",
                ),
                (
                    "Indecision repartie",
                    long_legged,
                    ctx.params.weights.symmetry,
                    f"meches {candle.lower_wick_ratio * 100:.0f}% / {candle.upper_wick_ratio * 100:.0f}% du range"
                    + (" (long-legged)" if long_legged else ""),
                ),
            ],
            parameters=cfg.model_dump(),
            levels={"PATTERN_HIGH": candle.high, "PATTERN_LOW": candle.low},
            breakout_levels=[
                ("PATTERN_HIGH", candle.high, "BULLISH"),
                ("PATTERN_LOW", candle.low, "BEARISH"),
            ],
            detected_at_bar_time=candle.time,
            watch_from_index=index,
            max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
        )

    return _scan_candles(ctx, build)
