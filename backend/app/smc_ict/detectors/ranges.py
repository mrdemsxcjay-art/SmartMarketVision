"""Dealing range (§14), premium / discount (§15) and displacement (§13).

The dealing range is never arbitrary. It is built from swings the Phase 1/2 pivot
detector already confirmed: the highest confirmed swing high and the lowest
confirmed swing low inside ``dealing_range.lookback_bars``, provided the two are
at least ``min_span_atr`` ATR apart and there is at least one swing on each side.
If no such pair exists, **no range is produced at all** - the engine refuses to
invent a high and a low just to paint a premium/discount background.

Premium / discount is then pure proportion: ``position = (close - low) / (high - low)``.
Above ``premium_zone`` the price is premium, below ``discount_zone`` it is
discount, inside the equilibrium band it is at equilibrium; in between, the range
is reported without a zone label because the price is simply mid-range.

Displacement is a measurement, never an adjective: see
:func:`app.smc_ict.measures.displacement_of` for the exposed numbers.
"""

from __future__ import annotations

from app.price_action.candles import ge, gt, le
from app.smc_ict.measures import displacement_of, is_displacement
from app.smc_ict.models import ScanContext, SmcCandidate


def _range_coordinates(
    ctx: ScanContext,
    *,
    high: float,
    low: float,
    equilibrium: float,
    source_high_index: int,
    source_low_index: int,
    newest: int,
) -> list[tuple[int, float, str, str]]:
    """Drawable anchors of the range, each one on a candle that really contains it.

    The high and the low come from their own swing candles. The equilibrium is a
    price level, not a candle: it is anchored on the newest candle that actually
    contains it, and if none does, no equilibrium point is drawn at all rather
    than pointing at a price the candle never traded.
    """
    points: list[tuple[int, float, str, str]] = [
        (source_high_index, high, "RANGE_HIGH", "dealing range high"),
        (source_low_index, low, "RANGE_LOW", "dealing range low"),
    ]
    for index in range(newest, -1, -1):
        bar = ctx.metrics[index]
        if le(bar.low, equilibrium) and le(equilibrium, bar.high):
            points.append((index, equilibrium, "EQUILIBRIUM", "dealing range equilibrium"))
            break
    return points


def detect_dealing_range(ctx: ScanContext) -> SmcCandidate | None:
    """§14 - the dealing range, with its sources and its equilibrium."""
    params = ctx.params
    dr = params.dealing_range
    weights = params.weights
    if len(ctx.metrics) < params.global_.min_bars_required:
        return None

    newest = len(ctx.metrics) - 1
    oldest = max(0, newest - dr.lookback_bars)
    highs = [s for s in ctx.swings if s.is_high and s.index >= oldest and s.confirmed_at_index <= newest]
    lows = [s for s in ctx.swings if not s.is_high and s.index >= oldest and s.confirmed_at_index <= newest]
    if len(highs) < dr.min_swings_each_side or len(lows) < dr.min_swings_each_side:
        return None

    source_high = max(highs, key=lambda s: s.price)
    source_low = min(lows, key=lambda s: s.price)
    high, low = source_high.price, source_low.price
    span = high - low
    floor = dr.min_span_atr * ctx.atr
    if not ge(span, floor) or le(span, 0.0):
        return None

    close = ctx.metrics[newest].close
    if dr.require_price_inside and not (le(low, close) and le(close, high)):
        return None

    equilibrium = (high + low) / 2.0
    position = (close - low) / span
    criteria = [
        (
            "Sommets et creux confirmés disponibles",
            True,
            weights.structure,
            f"{len(highs)} sommet(s) et {len(lows)} creux dans {dr.lookback_bars} bougies",
        ),
        (
            "Source du haut et du bas explicite",
            True,
            weights.structure,
            f"haut = SWING_HIGH #{source_high.index} à {high:.5f}, "
            f"bas = SWING_LOW #{source_low.index} à {low:.5f}",
        ),
        (
            "Hauteur minimale du range",
            ge(span, floor),
            weights.geometry,
            f"hauteur {ctx.pips(span):.2f} pip = {ctx.atr_multiple(span):.2f} ATR "
            f"(seuil {dr.min_span_atr} ATR), équilibre {equilibrium:.5f}",
        ),
        (
            "Prix à l'intérieur du range",
            le(low, close) and le(close, high),
            weights.context,
            f"clôture {close:.5f}, position {position * 100:.1f}% du range",
        ),
    ]
    return SmcCandidate(
        pattern="DEALING_RANGE",
        direction="NEUTRAL",
        index=newest,
        time=ctx.metrics[newest].time,
        criteria=criteria,
        evidence=[
            f"Range de travail {low:.5f} - {high:.5f} ({ctx.pips(span):.2f} pip, "
            f"{ctx.atr_multiple(span):.2f} ATR)",
            f"Source : sommet #{source_high.index} (force {source_high.strength}) et "
            f"creux #{source_low.index} (force {source_low.strength})",
            f"Équilibre (50%) : {equilibrium:.5f} - position actuelle {position * 100:.1f}%",
            "Sélection documentée : plus haut sommet et plus bas creux confirmés de la fenêtre, "
            "aucune borne arbitraire",
        ],
        measurements={
            "span_pips": round(ctx.pips(span), 2),
            "span_atr": round(ctx.atr_multiple(span), 4),
            "equilibrium": round(equilibrium, 8),
            "position": round(position, 6),
            "source_high_index": source_high.index,
            "source_low_index": source_low.index,
            "lookback_bars": dr.lookback_bars,
            "swings_high": len(highs),
            "swings_low": len(lows),
        },
        levels={
            "RANGE_HIGH": round(high, 8),
            "RANGE_LOW": round(low, 8),
            "EQUILIBRIUM": round(equilibrium, 8),
        },
        zones=[
            {
                "time_start": ctx.metrics[oldest].time,
                "time_end": ctx.metrics[newest].time,
                "price_top": round(high, 8),
                "price_bottom": round(equilibrium, 8),
                "label": "PREMIUM",
                "kind": "PREMIUM_ZONE",
            },
            {
                "time_start": ctx.metrics[oldest].time,
                "time_end": ctx.metrics[newest].time,
                "price_top": round(equilibrium, 8),
                "price_bottom": round(low, 8),
                "label": "DISCOUNT",
                "kind": "DISCOUNT_ZONE",
            },
        ],
        markers=[
            {
                "time": ctx.metrics[newest].time,
                "price": equilibrium,
                "position": "aboveBar",
                "shape": "square",
                "label": "EQ",
                "kind": "NEUTRAL",
            }
        ],
        coordinates=_range_coordinates(
            ctx,
            high=high,
            low=low,
            equilibrium=equilibrium,
            source_high_index=source_high.index,
            source_low_index=source_low.index,
            newest=newest,
        ),
        extra={
            "high": round(high, 8),
            "low": round(low, 8),
            "equilibrium": round(equilibrium, 8),
            "source_high": source_high.as_dict(),
            "source_low": source_low.as_dict(),
            "timeframe": ctx.timeframe,
            "position": round(position, 6),
        },
        source_from_index=min(source_high.index, source_low.index),
        family="RANGE",
    )


def detect_premium_discount(ctx: ScanContext, dealing_range: SmcCandidate | None) -> SmcCandidate | None:
    """§15 - premium / discount inside the real dealing range."""
    if dealing_range is None:
        return None
    params = ctx.params.premium_discount
    weights = ctx.params.weights
    high = float(dealing_range.levels["RANGE_HIGH"])
    low = float(dealing_range.levels["RANGE_LOW"])
    equilibrium = float(dealing_range.levels["EQUILIBRIUM"])
    span = high - low
    if le(span, 0.0):
        return None
    newest = len(ctx.metrics) - 1
    close = ctx.metrics[newest].close
    position = (close - low) / span

    if le(abs(position - 0.5), params.equilibrium_band):
        return None  # at equilibrium: no premium/discount claim is made
    if ge(position, params.premium_zone):
        pattern, label = "PREMIUM", "PREMIUM"
    elif le(position, params.discount_zone):
        pattern, label = "DISCOUNT", "DISCOUNT"
    else:
        return None  # mid-range: no zone label is claimed

    criteria = [
        (
            f"Position mesurée : {position * 100:.1f}% du range",
            True,
            weights.geometry,
            f"clôture {close:.5f} dans [{low:.5f} - {high:.5f}]",
        ),
        (
            f"Seuil {'premium' if pattern == 'PREMIUM' else 'discount'} respecté",
            True,
            weights.context,
            f"seuil premium {params.premium_zone}, seuil discount {params.discount_zone}, "
            f"bande d'équilibre ±{params.equilibrium_band}",
        ),
        (
            "Range de travail réel",
            True,
            weights.structure,
            f"range {low:.5f} - {high:.5f} issu des swings "
            f"#{dealing_range.extra['source_low']['index']} et #{dealing_range.extra['source_high']['index']}",
        ),
    ]
    return SmcCandidate(
        pattern=pattern,
        direction="NEUTRAL",
        index=newest,
        time=ctx.metrics[newest].time,
        criteria=criteria,
        evidence=[
            f"Prix en zone {label} du range de travail : position {position * 100:.1f}%",
            f"Range {low:.5f} - {high:.5f}, équilibre {equilibrium:.5f}",
            "Lecture purement proportionnelle : aucune projection de prix, aucun signal",
        ],
        measurements={
            "position": round(position, 6),
            "zone": label,
            "premium_zone": params.premium_zone,
            "discount_zone": params.discount_zone,
            "equilibrium_band": params.equilibrium_band,
        },
        levels={
            "RANGE_HIGH": round(high, 8),
            "RANGE_LOW": round(low, 8),
            "EQUILIBRIUM": round(equilibrium, 8),
            "POSITION": round(position, 6),
        },
        zones=[
            {
                "time_start": ctx.metrics[newest].time,
                "time_end": ctx.metrics[newest].time,
                "price_top": round(high, 8),
                "price_bottom": round(low, 8),
                "label": label,
                "kind": "PREMIUM" if pattern == "PREMIUM" else "DISCOUNT",
            }
        ],
        markers=[],
        coordinates=[(newest, close, label, f"{label} position")],
        extra={"zone": label, "position": round(position, 6), "range_index": dealing_range.index},
        source_from_index=dealing_range.source_from_index,
        family="RANGE",
    )


def detect_displacement(ctx: ScanContext) -> list[SmcCandidate]:
    """§13 - displacement candles of the live window, with every measure exposed."""
    params = ctx.params
    if len(ctx.metrics) < params.global_.min_bars_required:
        return []

    newest = len(ctx.metrics) - 1
    oldest = max(0, newest - params.global_.scan_bars + 1)
    out: list[SmcCandidate] = []
    for index in range(oldest, newest + 1):
        passed, measures = is_displacement(ctx, index)
        if not passed:
            continue
        bar = ctx.metrics[index]
        direction = "BULLISH" if ge(bar.close, bar.open) else "BEARISH"
        criteria = [
            (
                "Range de la bougie",
                True,
                params.weights.displacement,
                f"{measures['range_pips']} pip = {measures['range_atr']} ATR "
                f"(seuil {params.displacement.min_range_pips} pips / {params.displacement.min_range_atr} ATR)",
            ),
            (
                "Corps dominant",
                True,
                params.weights.displacement,
                f"corps/range {measures['body_ratio']} (seuil {params.displacement.min_body_ratio})",
            ),
            (
                "Progression au-delà de l'extrême précédent",
                True,
                params.weights.displacement,
                f"{measures['progression_pips']} pip ({measures['progression_atr']} ATR) "
                f"au-delà de {measures['previous_extreme']}",
            ),
        ]
        out.append(
            SmcCandidate(
                pattern="DISPLACEMENT",
                direction=direction,
                index=index,
                time=bar.time,
                criteria=criteria,
                evidence=[
                    f"Bougie {index} : range {measures['range_pips']} pip ({measures['range_atr']} ATR), "
                    f"corps/range {measures['body_ratio']}",
                    f"Progression {measures['progression_pips']} pip au-delà de l'extrême de la bougie "
                    f"précédente ({measures['previous_extreme']})",
                    f"Trace sur {params.displacement.lookback_bars} bougies : efficacité {measures['efficiency']}, "
                    f"{measures['same_direction_bars']} bougie(s) dans le même sens",
                    "Aucune notion de « grosse bougie » : seules les mesures ci-dessus sont utilisées",
                ],
                measurements=measures,
                levels={
                    "CANDLE_OPEN": round(bar.open, 8),
                    "CANDLE_CLOSE": round(bar.close, 8),
                    "CANDLE_HIGH": round(bar.high, 8),
                    "CANDLE_LOW": round(bar.low, 8),
                },
                zones=[
                    {
                        "time_start": bar.time,
                        "time_end": bar.time,
                        "price_top": round(bar.high, 8),
                        "price_bottom": round(bar.low, 8),
                        "label": "DISPLACEMENT",
                        "kind": "DISPLACEMENT",
                    }
                ],
                markers=[
                    {
                        "time": bar.time,
                        "price": bar.close,
                        "position": "aboveBar" if direction == "BEARISH" else "belowBar",
                        "shape": "arrowDown" if direction == "BEARISH" else "arrowUp",
                        "label": "DISP",
                        "kind": "HIGH" if direction == "BEARISH" else "LOW",
                    }
                ],
                coordinates=[(index, bar.close, "DISPLACEMENT", "displacement close")],
                extra={"measures": measures, "displacement_measure": measures},
                source_from_index=index,
                family="RANGE",
            )
        )
    return out
