"""Structural price-action events: impulsion, consolidation, rejection, failed
breakout.

These are not candlesticks: they describe *what the market is doing* at the time
a candlestick pattern appears, and every one of them is measurable.

Reuse, not duplication
----------------------
* ``REJECTION`` consumes the **real levels** produced by the chartist engine
  (support, resistance, rectangle edges, channels): the price-action engine never
  invents its own level engine;
* ``FAILED_BREAKOUT`` consumes the **breakout** already confirmed by Phase 2 (its
  level, its direction, its candle) and only decides whether price came back
  inside the level afterwards. There is exactly one breakout mechanism in this
  project, and it is not in this module.
"""

from __future__ import annotations

import statistics

from app.patterns.models import Candidate
from app.price_action.candles import CandleMetrics, ge, gt, le, lt, pips
from app.price_action.models import BreakoutRef, LevelRef, ScanContext


def _as_marker(metric: CandleMetrics, role: str, is_high: bool) -> dict[str, object]:
    return {
        "index": metric.index,
        "time": metric.time,
        "price": metric.high if is_high else metric.low,
        "type": "HIGH" if is_high else "LOW",
        "is_high": is_high,
        "kind": "HIGH" if is_high else "LOW",
        "role": role,
    }


# ---------------------------------------------------------------------- impulse
def detect_impulsion(ctx: ScanContext) -> list[Candidate]:
    """A contiguous directional run whose move is big **relative to volatility**.

    Measured, not interpreted:

    * the run = consecutive closed bars moving in the same direction, ending at the
      last closed bar (so a still-running move keeps the same anchor bar);
    * net move = close of the last bar - open of the first bar, compared with
      ``max(impulse_min_move_pips, impulse_min_move_atr x ATR)``;
    * efficiency = |net move| / sum of the bar-to-bar moves (a clean move, not chop);
    * adverse excursion = deepest pullback inside the run, as a share of the move.

    This is a *state*: it is reported while it is true, never once per bar.
    """
    cfg = ctx.params.structure
    pip_size = ctx.pip_size
    metrics = ctx.metrics
    if len(metrics) < cfg.impulse_min_bars:
        return []

    last = metrics[-1]
    if last.close == last.open:
        return []
    sign = 1.0 if last.close > last.open else -1.0
    limit = cfg.impulse_max_lookback_bars
    start = len(metrics) - 1
    while (
        start - 1 >= 0
        and (len(metrics) - 1 - (start - 1)) < limit
        and (metrics[start - 1].close - metrics[start - 1].open) * sign > 0
    ):
        start -= 1

    run = metrics[start:]
    if len(run) < cfg.impulse_min_bars:
        return []

    net = run[-1].close - run[0].open
    if net * sign <= 0:
        return []
    absolute = abs(net)
    min_move = max(
        cfg.impulse_min_move_pips * pip_size, cfg.impulse_min_move_atr * max(ctx.atr, run[-1].range)
    )
    if lt(absolute, min_move):
        return []

    steps = [abs(run[0].close - run[0].open)] + [
        abs(run[i].close - run[i - 1].close) for i in range(1, len(run))
    ]
    travelled = sum(steps)
    efficiency = absolute / travelled if travelled > 0 else 0.0

    extreme = run[0].close if sign > 0 else run[0].close
    worst = 0.0
    for metric in run:
        if sign > 0:
            worst = max(worst, (extreme - metric.low) / absolute)
            extreme = max(extreme, metric.close)
        else:
            worst = max(worst, (metric.high - extreme) / absolute)
            extreme = min(extreme, metric.close)
    if lt(efficiency, cfg.impulse_min_efficiency) or gt(worst, cfg.impulse_max_pullback_ratio):
        return []

    direction = "BULLISH" if net > 0 else "BEARISH"
    first, last_bar = run[0], run[-1]
    return [
        Candidate(
            pattern="IMPULSION",
            direction=direction,
            pivots=[],
            evidence=[
                f"Mouvement {'haussier' if net > 0 else 'baissier'} de {pips(absolute, pip_size):.1f} pips "
                f"sur {len(run)} bougies alignees (close {first.close} -> {last_bar.close})",
                f"Du minimum requis : {pips(min_move, pip_size):.1f} pips "
                f"(max entre plancher en pips et part d'ATR {ctx.atr:.6f})",
                f"Efficacite {efficiency * 100:.0f}% : {pips(travelled, pip_size):.1f} pips parcourus "
                "pour le deplacement net (mesure anti-chop)",
                f"Repli maximal dans le mouvement : {worst * 100:.0f}% du deplacement",
                "Etat de marche, pas un signal : aucun niveau d'entree n'en est deduit",
            ],
            evidence_points={
                "pattern": "IMPULSION",
                "pattern_kind": "STATE",
                "measurements": {
                    "net_move_pips": round(pips(absolute, pip_size), 1),
                    "travelled_pips": round(pips(travelled, pip_size), 1),
                    "efficiency": round(efficiency, 3),
                    "max_pullback_ratio": round(worst, 3),
                    "bars": len(run),
                    "start_open": first.open,
                    "end_close": last_bar.close,
                    "required_pips": round(pips(min_move, pip_size), 1),
                    "atr": round(ctx.atr, 6),
                },
                "pivots": {
                    "START": _as_marker(first, "DEBUT", net < 0),
                    "END": _as_marker(last_bar, "FIN", net > 0),
                },
                "roles": {"START": "D", "END": "F"},
            },
            factors=[
                (
                    "Deplacement net suffisant",
                    absolute >= min_move * 1.4,
                    ctx.params.weights.relative_size,
                    f"{pips(absolute, pip_size):.1f} pips sur {len(run)} bougies "
                    f"(minimum {pips(min_move, pip_size):.1f})",
                ),
                (
                    "Deplacement efficace",
                    efficiency >= cfg.impulse_min_efficiency * 1.05,
                    ctx.params.weights.structure_clear,
                    f"efficacite {efficiency * 100:.0f}% (minimum {cfg.impulse_min_efficiency * 100:.0f}%)",
                ),
                (
                    "Repli contenu",
                    worst <= cfg.impulse_max_pullback_ratio * 0.7,
                    ctx.params.weights.symmetry,
                    f"repli maximal {worst * 100:.0f}% (maximum {cfg.impulse_max_pullback_ratio * 100:.0f}%)",
                ),
                (
                    "Bougies alignees",
                    len(run) >= cfg.impulse_min_bars + 1,
                    ctx.params.weights.candle_geometry,
                    f"{len(run)} bougies dans le meme sens (minimum {cfg.impulse_min_bars})",
                ),
            ],
            parameters=cfg.model_dump(),
            levels={"IMPULSE_START": first.open, "IMPULSE_END": last_bar.close},
            zones=[
                {
                    "time_start": first.time,
                    "time_end": last_bar.time,
                    "price_top": max(first.open, last_bar.close, max(m.high for m in run)),
                    "price_bottom": min(first.open, last_bar.close, min(m.low for m in run)),
                    "label": "IMPULSION",
                    "kind": "STRUCTURE",
                }
            ],
            breakout_levels=[],
            detected_at_bar_time=first.time,
            watch_from_index=len(metrics) - 1,
            max_bars_to_confirm=None,
            notes=["etat de marche mesure sur des bougies cloturees"],
        )
    ]


# ---------------------------------------------------------------- consolidation
def detect_consolidation(ctx: ScanContext) -> list[Candidate]:
    """A measurable compression: the recent range collapses and price stays boxed.

    * box = [min low, max high] of the last ``consolidation_box_bars`` closed bars;
    * containment run = consecutive bars ending at the last closed bar that stay
      inside the box (plus a tolerance), never longer than
      ``consolidation_window_bars`` and never shorter than ``consolidation_min_bars``;
    * compression = mean range of the run / mean range of the reference window
      before it (``consolidation_reference_bars``);
    * box height compared with the reference volatility (``consolidation_max_height_atr``).

    The identity of the state is the **first bar of the containment run**, so a box
    that keeps holding is refreshed, never duplicated.
    """
    cfg = ctx.params.structure
    pip_size = ctx.pip_size
    metrics = ctx.metrics
    box_bars = cfg.consolidation_box_bars
    if len(metrics) < box_bars + 3:
        return []

    box_window = metrics[-box_bars:]
    box_high = max(m.high for m in box_window)
    box_low = min(m.low for m in box_window)
    tolerance = cfg.consolidation_tolerance_pips * pip_size

    last_index = len(metrics) - 1
    start = last_index
    while (
        start - 1 >= 0
        and (last_index - (start - 1)) < cfg.consolidation_window_bars
        and metrics[start - 1].high <= box_high + tolerance
        and metrics[start - 1].low >= box_low - tolerance
    ):
        start -= 1
    run = metrics[start:]
    if len(run) < cfg.consolidation_min_bars:
        return []

    reference = metrics[max(0, start - cfg.consolidation_reference_bars) : start]
    if len(reference) < 3:
        return []
    reference_mean = statistics.fmean(m.range for m in reference)
    if reference_mean <= 0:
        return []

    current_mean = statistics.fmean(m.range for m in run)
    compression = current_mean / reference_mean
    height = box_high - box_low
    max_height = cfg.consolidation_max_height_atr * max(reference_mean, ctx.atr)
    if gt(compression, cfg.consolidation_max_compression) or gt(height, max_height):
        return []

    return [
        Candidate(
            pattern="CONSOLIDATION",
            direction="NEUTRAL",
            pivots=[],
            evidence=[
                f"Range moyen comprime : {pips(current_mean, pip_size):.1f} pips contre "
                f"{pips(reference_mean, pip_size):.1f} pips de reference (x{compression:.2f})",
                f"Boite de {pips(height, pip_size):.1f} pips entre {box_low} et {box_high}",
                f"Contention : {len(run)} bougies consecutives dans la boite depuis la bougie {run[0].time}",
                "Etat de marche mesure, jamais une direction supposee",
            ],
            evidence_points={
                "pattern": "CONSOLIDATION",
                "pattern_kind": "STATE",
                "measurements": {
                    "compression": round(compression, 3),
                    "max_compression": cfg.consolidation_max_compression,
                    "box_height_pips": round(pips(height, pip_size), 1),
                    "max_height_pips": round(pips(max_height, pip_size), 1),
                    "containment_bars": len(run),
                    "reference_bars": len(reference),
                    "box_high": box_high,
                    "box_low": box_low,
                    "atr": round(ctx.atr, 6),
                },
                "pivots": {
                    "BOX_HIGH": _as_marker(max(box_window, key=lambda m: m.high), "HAUT BOITE", True),
                    "BOX_LOW": _as_marker(min(box_window, key=lambda m: m.low), "BAS BOITE", False),
                },
                "roles": {"BOX_HIGH": "H", "BOX_LOW": "B"},
            },
            factors=[
                (
                    "Compression du range",
                    compression <= cfg.consolidation_max_compression * 0.8,
                    ctx.params.weights.relative_size,
                    f"range moyen {pips(current_mean, pip_size):.1f} pips contre "
                    f"{pips(reference_mean, pip_size):.1f} (x{compression:.2f}, maximum "
                    f"x{cfg.consolidation_max_compression:.2f})",
                ),
                (
                    "Boite resserree",
                    height <= max_height * 0.8,
                    ctx.params.weights.structure_clear,
                    f"hauteur {pips(height, pip_size):.1f} pips (maximum {pips(max_height, pip_size):.1f})",
                ),
                (
                    "Contention durable",
                    len(run) >= cfg.consolidation_min_bars + 2,
                    ctx.params.weights.time_context,
                    f"{len(run)} bougies dans la boite (minimum {cfg.consolidation_min_bars})",
                ),
            ],
            parameters=cfg.model_dump(),
            levels={"BOX_HIGH": box_high, "BOX_LOW": box_low},
            zones=[
                {
                    "time_start": run[0].time,
                    "time_end": run[-1].time,
                    "price_top": box_high,
                    "price_bottom": box_low,
                    "label": "CONSOLIDATION",
                    "kind": "STRUCTURE",
                }
            ],
            breakout_levels=[],
            detected_at_bar_time=run[0].time,
            watch_from_index=last_index,
            max_bars_to_confirm=None,
            notes=["etat de marche mesure sur des bougies cloturees"],
        )
    ]


def _level_identity(level: LevelRef) -> str:
    """Real identity of a chartist level, as the engine itself publishes it.

    Three real values, in the order that tells them apart:

    * the ``kind`` - the same price is published twice by the chartist engine when a
      formation breaks a level of its own (``NECKLINE`` / ``CHANNEL`` at the market
      price, then the ``BREAKOUT`` reference to that same level): those are two
      distinct references and must not be conflated;
    * the ``source_id`` - the Phase 2 detection that published the level, so two
      neighbouring supports (1.10000 and 1.10003) stay distinct even when neither
      has a dominant kind;
    * the price, rounded to 6 decimals - the convention ``_levels_from_chartist``
      already uses to recognise "the same level", which absorbs the float noise of
      a price recomputed from another candle path.

    No threshold, no criterion, no confidence is involved: only what the level is.
    """
    origin = level.source_id or level.source
    return f"{level.kind}:{origin}@{round(level.price, 6)}"


def _broken_level_identity(ref: BreakoutRef) -> str:
    """Real identity of the level a breakout broke: type + publishing detection + price.

    Two levels broken on the same candle (the case measured in the audit) differ by
    their type and/or their publishing detection, never by the failure candle.
    """
    return f"{ref.level_type}:{ref.parent_id}@{round(ref.level, 6)}"


# --------------------------------------------------------------------- rejection
def detect_rejection(ctx: ScanContext, levels: list[LevelRef]) -> list[Candidate]:
    """A wick reaches a **real level** and the candle closes back away from it.

    Without a real level (support/resistance or a chartist boundary produced by
    Phase 2), nothing is reported: a "rejection" of nothing would be a fiction.
    """
    cfg = ctx.params.structure
    pip_size = ctx.pip_size
    if not levels or not ctx.metrics:
        return []

    current = ctx.metrics[-1]
    candidates: list[Candidate] = []
    for level in levels:
        if level.age_bars is not None and level.age_bars > ctx.params.levels.max_level_age_bars:
            continue

        if level.kind == "SUPPORT":
            side = "BELOW"  # the level is a floor: the wick goes under it
        elif level.kind == "RESISTANCE":
            side = "ABOVE"
        else:
            # rectangle edges / channels / breakout levels can be tested from either side
            side = "ABOVE" if current.close < level.price else "BELOW"

        if side == "ABOVE":
            wick_extreme, rejection_wick = current.high, current.upper_wick
            distance = wick_extreme - level.price
            close_distance = level.price - current.close
            direction = "BEARISH"
            factors_side = "vers le haut"
        else:
            wick_extreme, rejection_wick = current.low, current.lower_wick
            distance = level.price - wick_extreme
            close_distance = current.close - level.price
            direction = "BULLISH"
            factors_side = "vers le bas"

        tolerance = max(level.tolerance, ctx.min_size(
            cfg.rejection_level_tolerance_pips, cfg.rejection_level_tolerance_atr
        ))
        if gt(abs(distance), tolerance):
            continue
        if lt(close_distance, cfg.rejection_min_close_distance_pips * pip_size):
            continue
        if current.range <= 0 or lt(rejection_wick / current.range, cfg.rejection_min_wick_range_ratio):
            continue

        candidates.append(
            Candidate(
                pattern="REJECTION",
                direction=direction,
                pivots=[],
                evidence=[
                    f"Niveau reel teste : {level.kind} a {level.price:.{ctx.digits}f} "
                    f"(source {level.source})",
                    f"Meche {factors_side} jusqu'a {wick_extreme}, ecart au niveau "
                    f"{pips(abs(distance), pip_size):.1f} pip (tolerance {pips(tolerance, pip_size):.1f})",
                    f"Cloture {current.close} a {pips(close_distance, pip_size):.1f} pips du niveau",
                    f"Bougie {current.index} : meche de rejet = {rejection_wick / current.range * 100:.0f}% "
                    f"du range de {pips(current.range, pip_size):.1f} pips",
                ],
                evidence_points={
                    "pattern": "REJECTION",
                    "pattern_kind": "STRUCTURE",
                    "level": level.as_dict(),
                    "current_candle": current.as_dict(),
                    "measurements": {
                        "level_price": level.price,
                        "level_kind": level.kind,
                        "distance_to_level_pips": round(pips(abs(distance), pip_size), 2),
                        "close_distance_pips": round(pips(close_distance, pip_size), 2),
                        "rejection_wick_ratio": round(rejection_wick / current.range, 3),
                        "tolerance_pips": round(pips(tolerance, pip_size), 2),
                        "side": side,
                        "atr": round(ctx.atr, 6),
                    },
                    "pivots": {"PATTERN": _as_marker(current, "REJET", side == "ABOVE")},
                    "roles": {"PATTERN": "REJ"},
                },
                factors=[
                    (
                        "Meche au contact du niveau",
                        abs(distance) <= tolerance * 0.5,
                        ctx.params.weights.level_context,
                        f"extreme {wick_extreme} contre niveau {level.price:.{ctx.digits}f} "
                        f"(ecart {pips(abs(distance), pip_size):.1f} pip)",
                    ),
                    (
                        "Cloture eloignee du niveau",
                        close_distance >= cfg.rejection_min_close_distance_pips * pip_size * 1.5,
                        ctx.params.weights.level_context,
                        f"cloture a {pips(close_distance, pip_size):.1f} pips du niveau",
                    ),
                    (
                        "Rejet visible dans la bougie",
                        rejection_wick / current.range >= cfg.rejection_min_wick_range_ratio * 1.2,
                        ctx.params.weights.candle_geometry,
                        f"meche de rejet {rejection_wick / current.range * 100:.0f}% du range",
                    ),
                    (
                        "Niveau reel et recent",
                        level.age_bars is None or level.age_bars <= ctx.params.levels.max_level_age_bars,
                        ctx.params.weights.no_conflict,
                        f"niveau {level.kind} de {level.source} "
                        f"(age {level.age_bars if level.age_bars is not None else 'n/a'} bougies)",
                    ),
                ],
                parameters=cfg.model_dump(),
                levels={"LEVEL": level.price},
                breakout_levels=[],
                level_identity=_level_identity(level),
                detected_at_bar_time=current.time,
                watch_from_index=len(ctx.metrics) - 1,
                max_bars_to_confirm=ctx.params.globals.max_bars_to_confirm,
                notes=[f"niveau fourni par {level.source}"],
            )
        )
        if len(candidates) >= 2:
            break
    return candidates


# --------------------------------------------------------------- failed breakout
def detect_failed_breakout(ctx: ScanContext, breakouts: list[BreakoutRef]) -> list[Candidate]:
    """After a confirmed breakout (Phase 2), price comes back inside the level.

    Sequence, on closed candles only:

    ``BREAKOUT`` (chartist engine) -> price returns beyond the level -> ``FAILED_BREAKOUT``.

    The breakout itself is never recomputed here: it is consumed from the chartist
    engine, so the two engines can never contradict each other on what a breakout
    is.
    """
    cfg = ctx.params.structure
    pip_size = ctx.pip_size
    if not breakouts or not ctx.metrics:
        return []

    metrics = ctx.metrics
    results: list[Candidate] = []
    for ref in breakouts:
        start_index = next((i for i, m in enumerate(metrics) if m.time >= ref.breakout_time), None)
        if start_index is None:
            continue

        failure: tuple[int, CandleMetrics] | None = None
        for i in range(start_index + 1, len(metrics)):
            if i - start_index > cfg.failed_breakout_max_bars_to_fail:
                break
            candle = metrics[i]
            if ref.direction == "BULLISH":
                # a bullish break fails when price closes back below the level
                if candle.close < ref.level - cfg.failed_breakout_min_return_pips * pip_size:
                    failure = (i, candle)
                    break
            elif candle.close > ref.level + cfg.failed_breakout_min_return_pips * pip_size:
                failure = (i, candle)
                break
        if failure is None:
            continue

        index, candle = failure
        bars_after = index - start_index
        distance = abs(candle.close - ref.level)
        direction = "BEARISH" if ref.direction == "BULLISH" else "BULLISH"

        results.append(
            Candidate(
                pattern="FAILED_BREAKOUT",
                direction=direction,
                pivots=[],
                evidence=[
                    f"Cassure {ref.direction} confirmee par {ref.parent_pattern} : niveau {ref.level:.{ctx.digits}f} "
                    f"franchi a {ref.breakout_price} ({ref.level_type})",
                    f"Retour dans la zone : cloture {candle.close} a {pips(distance, pip_size):.1f} pips "
                    f"de l'autre cote du niveau, {bars_after} bougie(s) apres la cassure",
                    f"Bougie d'echec : {candle.time} (O {candle.open} C {candle.close})",
                    "La cassure n'a pas tenu : le niveau redevient la reference du marche",
                ],
                evidence_points={
                    "pattern": "FAILED_BREAKOUT",
                    "pattern_kind": "STRUCTURE",
                    "breakout": ref.as_dict(),
                    "breakout_level": ref.level,
                    "breakout_candle": ref.breakout_time,
                    "failure_candle": candle.time,
                    "return_price": candle.close,
                    "measurements": {
                        "breakout_level": ref.level,
                        "breakout_price": ref.breakout_price,
                        "return_price": candle.close,
                        "return_distance_pips": round(pips(distance, pip_size), 2),
                        "bars_after_breakout": bars_after,
                        "max_bars_to_fail": cfg.failed_breakout_max_bars_to_fail,
                        "breakout_direction": ref.direction,
                        "atr": round(ctx.atr, 6),
                    },
                    "pivots": {
                        "BREAKOUT": {
                            "index": start_index,
                            "time": metrics[start_index].time,
                            "price": ref.breakout_price,
                            "type": "HIGH" if ref.direction == "BULLISH" else "LOW",
                            "is_high": ref.direction == "BULLISH",
                            "kind": "HIGH" if ref.direction == "BULLISH" else "LOW",
                        },
                        "FAILURE": _as_marker(candle, "ECHEC", ref.direction == "BULLISH"),
                    },
                    "roles": {"BREAKOUT": "BO", "FAILURE": "FB"},
                },
                factors=[
                    (
                        "Cassure de reference reelle",
                        True,
                        ctx.params.weights.pattern_context,
                        f"{ref.level_type} {ref.level:.{ctx.digits}f} franchi le {ref.breakout_time} "
                        f"par {ref.parent_pattern}",
                    ),
                    (
                        "Retour effectif dans la zone",
                        distance >= cfg.failed_breakout_min_return_pips * pip_size * 2,
                        ctx.params.weights.level_context,
                        f"cloture a {pips(distance, pip_size):.1f} pips au-dela du niveau",
                    ),
                    (
                        "Echec rapide",
                        bars_after <= max(1, cfg.failed_breakout_max_bars_to_fail // 2),
                        ctx.params.weights.time_context,
                        f"{bars_after} bougie(s) apres la cassure",
                    ),
                    (
                        "Niveau redevient la reference",
                        True,
                        ctx.params.weights.structure_clear,
                        "la cloture repasse du cote d'origine du niveau",
                    ),
                ],
                parameters=cfg.model_dump(),
                levels={"BREAKOUT_LEVEL": ref.level, "FAILURE_CLOSE": candle.close},
                zones=[
                    {
                        "time_start": metrics[start_index].time,
                        "time_end": candle.time,
                        "price_top": max(ref.level, ref.breakout_price, candle.close),
                        "price_bottom": min(ref.level, ref.breakout_price, candle.close),
                        "label": "FAILED BREAKOUT",
                        "kind": "STRUCTURE",
                    }
                ],
                breakout_levels=[],
                detected_at_bar_time=candle.time,
                watch_from_index=index,
                max_bars_to_confirm=cfg.failed_breakout_max_bars_to_fail,
                extra_signature=[ref.breakout_time, candle.time],
                level_identity=_broken_level_identity(ref),
                notes=[f"breakout parent {ref.parent_id}"],
            )
        )
    return results
