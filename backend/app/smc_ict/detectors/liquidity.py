"""Liquidity detectors: equal highs/lows, liquidity pool estimates, sweeps.

The engine cannot see resting orders, and it never pretends to. What it can do
is measure geometry:

* **equal highs / lows** - several confirmed swing highs (or lows) sitting inside
  a tolerance band, separated by a real distance: a level price came back to;
* **liquidity pool ESTIMATE** (``LIQUIDITY_POOL_ESTIMATE``) - the inference that
  resting liquidity is *likely* around such a level, or around an old swing the
  market has not revisited. The word "estimate" is part of the pattern name on
  purpose, and every pool carries ``estimate: true`` plus the method that
  produced it;
* **liquidity sweep** - the three-step sequence, all of them required:
  (1) the candle's extreme goes beyond the level, (2) the same candle closes back
  on the other side, (3) the excursion is a genuine wick. Without step 2 it is a
  break, not a sweep, and it is not reported here.

Levels are never invented: they are the swings the Phase 1/2 pivot detector
confirmed, or the bands those swings define.
"""

from __future__ import annotations

from app.price_action.candles import ge, gt, le, lt
from app.smc_ict.models import ScanContext, SmcCandidate, SmcSwing


def _tolerance(ctx: ScanContext) -> float:
    params = ctx.params.equal_levels
    return ctx.min_size(params.tolerance_pips, params.tolerance_atr)


def cluster_equal_swings(ctx: ScanContext, is_high: bool) -> list[dict[str, object]]:
    """Group confirmed swings of one kind into near-equal clusters.

    A swing joins the running cluster while it stays inside the tolerance band of
    the cluster level, and at least ``min_separation_bars`` after the previous
    touch (two touches on neighbouring bars are one touch, not an equality).
    """
    params = ctx.params.equal_levels
    tolerance = _tolerance(ctx)
    swings = [s for s in ctx.swings if s.is_high is is_high]
    clusters: list[dict[str, object]] = []

    for swing in swings:
        joined = False
        for cluster in reversed(clusters):
            if swing.index - int(cluster["last_index"]) < params.min_separation_bars:
                continue
            touches = list(cluster["touches"]) + [swing]
            prices = [t.price for t in touches]
            # the band is bounded by the declared tolerance on the WHOLE cluster,
            # not only on its running mean: otherwise the first touch could drift
            # out of the band as the mean moved (and the published spread would
            # contradict the published tolerance).
            if gt(max(prices) - min(prices), tolerance):
                continue
            cluster["touches"] = touches
            cluster["level"] = sum(prices) / len(prices)
            cluster["last_index"] = swing.index
            cluster["span_bars"] = swing.index - int(cluster["first_index"])
            joined = True
            break
        if not joined:
            clusters.append(
                {
                    "touches": [swing],
                    "level": swing.price,
                    "first_index": swing.index,
                    "last_index": swing.index,
                    "span_bars": 0,
                    "is_high": is_high,
                }
            )

    kept: list[dict[str, object]] = []
    newest = len(ctx.metrics) - 1
    for cluster in clusters:
        touches = cluster["touches"]
        if len(touches) < params.min_touches:
            continue
        if int(cluster["span_bars"]) > params.max_separation_bars:
            continue
        if newest - int(cluster["last_index"]) > params.max_separation_bars:
            continue  # too old to matter any more
        kept.append(cluster)
    return kept


def detect_equal_levels(ctx: ScanContext) -> list[SmcCandidate]:
    """§6 - EQUAL_HIGH / EQUAL_LOW, with the tolerance and the touches returned."""
    params = ctx.params
    if len(ctx.metrics) < params.global_.min_bars_required:
        return []

    tolerance = _tolerance(ctx)
    out: list[SmcCandidate] = []
    for is_high in (True, False):
        for cluster in cluster_equal_swings(ctx, is_high):
            touches: list[SmcSwing] = cluster["touches"]
            level = float(cluster["level"])
            last = touches[-1]
            pattern = "EQUAL_HIGH" if is_high else "EQUAL_LOW"
            side = "ABOVE" if is_high else "BELOW"
            criteria = [
                (
                    f"{len(touches)} pivots dans la tolérance",
                    len(touches) >= params.equal_levels.min_touches,
                    params.weights.structure,
                    f"pivots {[round(t.price, 5) for t in touches]}",
                ),
                (
                    "Tolérance respectée",
                    True,
                    params.weights.geometry,
                    f"écart max {ctx.pips(max(t.price for t in touches) - min(t.price for t in touches)):.2f} pip "
                    f"pour une tolérance de {ctx.pips(tolerance):.2f} pip "
                    f"(max({params.equal_levels.tolerance_pips} pips, {params.equal_levels.tolerance_atr} ATR))",
                ),
                (
                    "Séparation suffisante",
                    int(cluster["span_bars"]) >= params.equal_levels.min_separation_bars,
                    params.weights.context,
                    f"{int(cluster['span_bars'])} bougie(s) entre le premier et le dernier contact "
                    f"(minimum {params.equal_levels.min_separation_bars})",
                ),
            ]
            out.append(
                SmcCandidate(
                    pattern=pattern,
                    direction="NEUTRAL",
                    index=last.index,
                    time=last.time,
                    criteria=criteria,
                    evidence=[
                        f"{len(touches)} sommets {'hauts' if is_high else 'bas'} quasi égaux autour de {level:.5f}",
                        "Prix touchés : " + ", ".join(f"{t.price:.5f} (#{t.index})" for t in touches),
                        f"Tolérance de mesure : {ctx.pips(tolerance):.2f} pip",
                        "Niveau côté " + side + " : zone de liquidité probable, jamais un ordre observé",
                    ],
                    measurements={
                        "touch_count": len(touches),
                        "tolerance_pips": round(ctx.pips(tolerance), 2),
                        "tolerance": round(tolerance, 8),
                        "span_bars": int(cluster["span_bars"]),
                        "spread_pips": round(
                            ctx.pips(max(t.price for t in touches) - min(t.price for t in touches)), 2
                        ),
                        "side": side,
                        "touches": [t.as_dict() for t in touches],
                        "liquidity_inference": True,
                    },
                    levels={"LEVEL": round(level, 8)},
                    zones=[
                        {
                            "time_start": touches[0].time,
                            "time_end": last.time,
                            "price_top": round(level + tolerance, 8),
                            "price_bottom": round(level - tolerance, 8),
                            "label": pattern,
                            "kind": "LIQUIDITY_LEVEL",
                        }
                    ],
                    markers=[
                        {
                            "time": last.time,
                            "price": level,
                            "position": "aboveBar" if is_high else "belowBar",
                            "shape": "circle",
                            "label": pattern,
                            "kind": "HIGH" if is_high else "LOW",
                        }
                    ],
                    coordinates=[
                        (t.index, t.price, "TOUCH", f"{pattern} touch") for t in touches
                    ],
                    extra={
                        "touches": [t.as_dict() for t in touches],
                        "timestamps": [t.iso for t in touches],
                        "prices": [t.price for t in touches],
                        "tolerance": round(tolerance, 8),
                        "side": side,
                    },
                    source_from_index=touches[0].index,
                    family="LIQUIDITY",
                )
            )
    return out


def _consumed(ctx: ScanContext, *, level: float, is_high: bool, after: int) -> bool:
    """True when price CLOSED beyond the level after it was formed.

    A close beyond the level means the resting liquidity has been taken; a wick
    beyond it is a sweep and keeps the level on the list (the sweep is the event
    we want to report, not a reason to forget the level).
    """
    buffer = ctx.params.sweep.reentry_buffer_pips * ctx.pip_size
    for bar in ctx.metrics[after + 1 :]:
        if is_high and gt(bar.close, level + buffer):
            return True
        if not is_high and lt(bar.close, level - buffer):
            return True
    return False


def detect_liquidity_pools(ctx: ScanContext) -> list[SmcCandidate]:
    """§7 - geometric inference of resting liquidity (always an ESTIMATE)."""
    params = ctx.params
    if len(ctx.metrics) < params.global_.min_bars_required:
        return []

    newest = len(ctx.metrics) - 1
    out: list[SmcCandidate] = []
    sources: list[dict[str, object]] = []

    if params.pools.use_equal_levels:
        for is_high in (True, False):
            for cluster in cluster_equal_swings(ctx, is_high):
                # a level price already CLOSED through is consumed: it is no longer
                # resting liquidity. A mere wick through it is a sweep, not a
                # consumption, and it must not remove the level from the list.
                if _consumed(
                    ctx,
                    level=float(cluster["level"]),
                    is_high=is_high,
                    after=int(cluster["last_index"]),
                ):
                    continue
                sources.append(
                    {
                        "kind": "EQUAL_HIGH" if is_high else "EQUAL_LOW",
                        "is_high": is_high,
                        "level": float(cluster["level"]),
                        "touches": len(cluster["touches"]),
                        "index": int(cluster["last_index"]),
                        "first_index": int(cluster["first_index"]),
                        "formed_at": int(cluster["last_index"]),
                        "anchor_index": int(cluster["last_index"]),
                        "anchor_price": float(cluster["touches"][-1].price),
                        "score": 2.0 + len(cluster["touches"]),
                    }
                )

    if params.pools.use_old_swings:
        for swing in ctx.swings:
            age = newest - swing.index
            if age < params.pools.old_swing_min_bars or age > params.pools.max_pool_age_bars:
                continue
            if _consumed(ctx, level=swing.price, is_high=swing.is_high, after=swing.index):
                continue
            sources.append(
                {
                    "kind": "OLD_SWING_HIGH" if swing.is_high else "OLD_SWING_LOW",
                    "is_high": swing.is_high,
                    "level": swing.price,
                    "touches": 1,
                    "index": swing.index,
                    "first_index": swing.index,
                    "formed_at": swing.index,
                    "anchor_index": swing.index,
                    "anchor_price": swing.price,
                    "score": 1.0 + swing.strength * 0.1,
                }
            )

    # strongest first, then most recent: the keep-list is deterministic
    sources.sort(key=lambda item: (-float(item["score"]), -int(item["index"])))
    tolerance = _tolerance(ctx)
    kept: list[dict[str, object]] = []
    for source in sources:
        duplicate = any(
            bool(source["is_high"]) == bool(other["is_high"])
            and le(abs(float(source["level"]) - float(other["level"])), tolerance)
            for other in kept
        )
        if duplicate:
            continue  # two swings at the same price are one pool, not two
        kept.append(source)
        if len(kept) >= params.pools.max_pools:
            break

    for source in kept:
        level = float(source["level"])
        is_high = bool(source["is_high"])
        age = newest - int(source["index"])
        # the level is the measured mean of the touches; the DRAWING anchor must be
        # a real candle: the touch whose own high/low encloses the level (nearest
        # first). A pool is never drawn on a candle that does not contain it.
        anchor_index = int(source.get("anchor_index", source["index"]))
        anchor_price = float(source.get("anchor_price", level))
        candidates_anchor = [s for s in ctx.swings if bool(s.is_high) is is_high]
        containing = [
            s
            for s in candidates_anchor
            if le(ctx.metrics[s.index].low, level) and le(level, ctx.metrics[s.index].high)
        ]
        if containing:
            nearest = min(containing, key=lambda s: (abs(s.index - int(source["index"])), -s.index))
            anchor_index, anchor_price = nearest.index, nearest.price
        side = "ABOVE" if is_high else "BELOW"
        criteria = [
            (
                "Source géométrique identifiée",
                True,
                params.weights.structure,
                f"{source['kind']} à {level:.5f} (#{source['index']}, {source['touches']} contact(s))",
            ),
            (
                "Niveau non consommé par le marché",
                True,
                params.weights.liquidity,
                f"aucune clôture au-delà du niveau depuis sa formation ({age} bougie(s), "
                f"tampon {params.sweep.reentry_buffer_pips} pip) : une mèche au-delà serait un balayage, "
                "pas une consommation",
            ),
            (
                "Estimation explicite",
                True,
                params.weights.context,
                "LIQUIDITY_POOL_ESTIMATE : inférence géométrique, les ordres réels ne sont pas observables",
            ),
        ]
        out.append(
            SmcCandidate(
                pattern="LIQUIDITY_POOL_ESTIMATE",
                direction="NEUTRAL",
                index=int(source["index"]),
                time=ctx.metrics[int(source["index"])].time,
                criteria=criteria,
                evidence=[
                    f"Zone de liquidité estimée autour de {level:.5f} ({source['kind']}, côté {side})",
                    f"Âge du niveau : {age} bougie(s), {source['touches']} contact(s) mesuré(s)",
                    "ESTIMATION : le moteur déduit une zone probable, il n'observe aucun ordre réel",
                ],
                measurements={
                    "estimate": True,
                    "method": str(source["kind"]),
                    "touch_count": int(source["touches"]),
                    "age_bars": age,
                    "side": side,
                    "score": round(float(source["score"]), 2),
                    "anchor_index": anchor_index,
                    "anchor_price": round(anchor_price, 8),
                },
                levels={"POOL_LEVEL": round(level, 8)},
                zones=[
                    {
                        "time_start": ctx.metrics[int(source["first_index"])].time,
                        "time_end": ctx.metrics[newest].time,
                        "price_top": round(level + _tolerance(ctx), 8),
                        "price_bottom": round(level - _tolerance(ctx), 8),
                        "label": "LIQUIDITY_POOL_ESTIMATE",
                        "kind": "LIQUIDITY_POOL",
                    }
                ],
                markers=[
                    {
                        "time": ctx.metrics[int(source["index"])].time,
                        "price": level,
                        "position": "aboveBar" if is_high else "belowBar",
                        "shape": "circle",
                        "label": "POOL",
                        "kind": "HIGH" if is_high else "LOW",
                    }
                ],
                coordinates=[(anchor_index, anchor_price, "POOL", "liquidity pool estimate")],
                extra={
                    "method": str(source["kind"]),
                    "estimate": True,
                    "side": side,
                    "age_bars": age,
                    "touch_count": int(source["touches"]),
                },
                source_from_index=int(source["first_index"]),
                family="LIQUIDITY",
            )
        )
    return out


def liquidity_levels(ctx: ScanContext, pools: list[SmcCandidate] | None = None) -> list[dict[str, object]]:
    """Levels a sweep can act on: estimated pools plus the two most recent swings."""
    levels: list[dict[str, object]] = []
    for pool in pools if pools is not None else detect_liquidity_pools(ctx):
        level = float(pool.levels["POOL_LEVEL"])
        method = str(pool.extra["method"])
        levels.append(
            {
                "level": level,
                "kind": method,
                "index": pool.index,
                "is_high": pool.extra["side"] == "ABOVE",
                "rank": 2 if method.startswith("EQUAL_") else 1,
                "touches": int(pool.measurements.get("touch_count", 1)),
            }
        )
    for is_high in (True, False):
        recent = [s for s in ctx.swings if s.is_high is is_high]
        if recent:
            swing = recent[-1]
            levels.append(
                {
                    "level": swing.price,
                    "kind": "RECENT_SWING",
                    "index": swing.index,
                    "is_high": is_high,
                    "rank": 0,
                    "touches": 1,
                }
            )
    return levels


def detect_liquidity_sweeps(ctx: ScanContext) -> list[SmcCandidate]:
    """§8 - sweep = pierce, close back on the rejected side, genuine wick."""
    params = ctx.params.sweep
    weights = ctx.params.weights
    if len(ctx.metrics) < ctx.params.global_.min_bars_required:
        return []

    levels = liquidity_levels(ctx)
    if not levels:
        return []

    newest = len(ctx.metrics) - 1
    oldest = max(0, newest - params.max_scan_bars + 1)
    penetration_floor = penetration_floor_for(ctx)
    reentry = params.reentry_buffer_pips * ctx.pip_size
    out: list[SmcCandidate] = []
    best: dict[tuple[int, str], tuple[tuple, SmcCandidate]] = {}

    for index in range(oldest, newest + 1):
        bar = ctx.metrics[index]
        for level in levels:
            price = float(level["level"])
            if index - int(level["index"]) > params.max_level_age_bars:
                continue
            for is_high in (True, False):
                if is_high is not bool(level["is_high"]):
                    continue
                if is_high:
                    extreme = bar.high
                    measured = bar.high - price
                    close_gap = price - bar.close
                else:
                    extreme = bar.low
                    measured = price - bar.low
                    close_gap = bar.close - price
                if not gt(measured, penetration_floor):
                    continue
                if not gt(close_gap, reentry):
                    continue  # step 2 is mandatory: no re-entry, no sweep
                share = measured / bar.range if bar.range > 0 else 0.0
                if not ge(share, params.min_wick_share):
                    continue

                direction = "BEARISH" if is_high else "BULLISH"
                side = "ABOVE" if is_high else "BELOW"
                kind = str(level["kind"])
                criteria = [
                    (
                        "Étape 1 - mèche au-delà du niveau",
                        gt(measured, penetration_floor),
                        weights.liquidity,
                        f"extrême {extreme:.5f} au-delà de {price:.5f} de {ctx.pips(measured):.2f} pip "
                        f"(seuil {ctx.pips(penetration_floor):.2f} pip)",
                    ),
                    (
                        "Étape 2 - réintégration (clôture de retour)",
                        gt(close_gap, reentry),
                        weights.structure,
                        f"clôture {bar.close:.5f} revenue de {ctx.pips(close_gap):.2f} pip du bon côté "
                        f"(seuil {ctx.pips(reentry):.2f} pip)",
                    ),
                    (
                        "Étape 3 - excursion réelle",
                        ge(share, params.min_wick_share),
                        weights.geometry,
                        f"l'excursion représente {share * 100:.1f}% du range (minimum {params.min_wick_share * 100:.0f}%)",
                    ),
                    (
                        "Niveau de liquidité identifié",
                        True,
                        weights.context,
                        f"{kind} à {price:.5f} (#{level['index']}), côté {side}",
                    ),
                ]
                candidate = SmcCandidate(
                        pattern="LIQUIDITY_SWEEP",
                        direction=direction,
                        index=index,
                        time=bar.time,
                        criteria=criteria,
                        evidence=[
                            f"Liquidité estimée côté {side} à {price:.5f} ({kind})",
                            f"Bougie {index} : extrême {extreme:.5f} ({ctx.pips(measured):.2f} pip au-delà), "
                            f"clôture {bar.close:.5f} revenue de {ctx.pips(close_gap):.2f} pip",
                            "Les trois étapes (dépassement, réintégration, excursion) sont requises : "
                            "sans réintégration, il s'agit d'une cassure, pas d'un balayage",
                            "Le niveau est une estimation géométrique, jamais un carnet d'ordres observé",
                        ],
                        measurements={
                            "penetration_pips": round(ctx.pips(measured), 2),
                            "penetration_atr": round(ctx.atr_multiple(measured), 4),
                            "reentry_pips": round(ctx.pips(close_gap), 2),
                            "excursion_share": round(share, 4),
                            "level_kind": kind,
                            "level_index": int(level["index"]),
                            "level_age_bars": index - int(level["index"]),
                            "side": side,
                            "estimate": True,
                        },
                        levels={
                            "LIQUIDITY_LEVEL": round(price, 8),
                            "EXTREME": round(extreme, 8),
                            "REENTRY": round(bar.close, 8),
                        },
                        zones=[
                            {
                                "time_start": bar.time,
                                "time_end": bar.time,
                                "price_top": round(max(extreme, bar.close), 8),
                                "price_bottom": round(min(extreme, bar.close), 8),
                                "label": "LIQUIDITY_SWEEP",
                                "kind": "SWEEP_EXCURSION",
                            }
                        ],
                        markers=[
                            {
                                "time": bar.time,
                                "price": extreme,
                                "position": "aboveBar" if is_high else "belowBar",
                                "shape": "circle",
                                "label": "SWEEP",
                                "kind": "HIGH" if is_high else "LOW",
                            }
                        ],
                        coordinates=[(index, extreme, "SWEEP_EXTREME", "sweep extreme")],
                        extra={
                            "estimate": True,
                            "liquidity_level": round(price, 8),
                            "sweep_candle": index,
                            "extreme_price": round(extreme, 8),
                            "reentry_price": round(bar.close, 8),
                            "reentry_timestamp": ctx.metrics[index].time,
                            "symbol": ctx.symbol,
                            "timeframe": ctx.timeframe,
                            "side": side,
                            "level_kind": kind,
                        },
                        source_from_index=int(level["index"]),
                        family="LIQUIDITY",
                    )
                # one sweep per candle and per side: the strongest level wins, so
                # three levels a pip apart never produce three identical events
                key = (index, direction)
                rank = (
                    int(level.get("rank", 0)),
                    int(level.get("touches", 1)),
                    round(candidate.measurements["penetration_pips"], 2),
                )
                if key not in best or rank > best[key][0]:
                    best[key] = (rank, candidate)

    out = [item[1] for item in best.values()]
    out.sort(key=lambda c: (c.index, c.direction))
    return out


def penetration_floor_for(ctx: ScanContext) -> float:
    """The penetration floor, exposed so the criteria can quote it verbatim."""
    params = ctx.params.sweep
    return ctx.min_size(params.min_penetration_pips, params.min_penetration_atr)
