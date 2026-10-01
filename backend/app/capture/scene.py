"""Scene builder (Phase 7) - turns real engine state into a drawable scene.

Sources of every element, without exception:

* candles            -> the real OHLC series of the pair/timeframe;
* confluence zone    -> the price cluster of the confluence (real detection prices);
* source detections  -> the levels/zones/markers of the three engines;
* context            -> the trend of the structure engine and the dealing range.

The builder also applies the overlay budget of 7.2: the main event first, then the
confluence, then the sources, then the context. Elements that do not fit are left
out - and the count of what was left out is reported in ``notes`` so the capture
never pretends it showed everything.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.capture.models import CaptureScene, Overlay, OverlayKind, OverlayPriority
from app.confluence.normalizer import reference_price as detection_price
from app.capture.params import CaptureParams
from app.confluence.models import ConfluenceGroup
from app.logging_conf import get_logger
from app.opportunities.models import Opportunity
from app.schemas.events import PatternDetection
from app.schemas.market import CandleSeries

logger = get_logger(__name__)

#: colours per engine family (the same vocabulary as the dashboard palette)
SOURCE_COLORS = {
    # real DetectionSource values published by the engines
    "CHART_PATTERN_ENGINE": "#f0a020",
    "PRICE_ACTION_ENGINE": "#4da3ff",
    "SMC_ICT_ENGINE": "#b46bff",
    # engines of the confluence chain itself
    "CONFLUENCE": "#ff5fa2",
    "OPPORTUNITY": "#25d07a",
    # aliases kept for readability in the code and in the tests
    "CHARTISTE": "#f0a020",
    "PRICE_ACTION": "#4da3ff",
    "SMC_ICT": "#b46bff",
}

ZONE_KINDS = {"FVG", "ORDER_BLOCK", "BREAKER", "DEALING_RANGE", "PREMIUM", "DISCOUNT", "EQUILIBRIUM"}
LEVEL_KINDS = {"BOS", "CHOCH", "MSS", "EQUAL_HIGH", "EQUAL_LOW", "LIQUIDITY_POOL", "SWING"}
MARKER_KINDS = {"LIQUIDITY_SWEEP", "DISPLACEMENT", "BREAK_CLOSE", "BROKEN_SWING"}


def build_scene(
    series: CandleSeries,
    *,
    timeframe: str | None = None,
    detections: list[PatternDetection] | None = None,
    confluences: list[ConfluenceGroup] | None = None,
    opportunity: Opportunity | None = None,
    price: float | None = None,
    params: CaptureParams,
    timestamp: datetime | None = None,
) -> CaptureScene:
    """Assemble the scene. ``detections`` are the objects the engines published."""
    candles = [candle for candle in series.candles if candle.closed]
    if params.layout.candle_count and len(candles) > params.layout.candle_count:
        candles = candles[-params.layout.candle_count :]
    timeframe_value = timeframe or series.timeframe.value
    reference = price if price is not None else (candles[-1].close if candles else None)

    scene = CaptureScene(
        symbol=series.symbol,
        timeframe=timeframe_value,
        candles=candles,
        title=f"{series.symbol} - {timeframe_value}",
        timestamp=timestamp or datetime.now(tz=timezone.utc),
        price=reference,
        footer=(
            "SMART MARKET VISION - observation uniquement : aucun ordre, aucun broker. "
            "Niveaux et zones issus des detections reelles des moteurs."
        ),
    )
    if not candles:
        scene.notes.append("aucune bougie cloturee : rien a dessiner")
        return scene

    dropped = {"context": 0, "sources": 0, "zones": 0, "levels": 0, "labels": 0}
    overlays: list[Overlay] = []

    # ---- priority 1 : the observation that carries the message
    if opportunity is not None:
        overlays.extend(_opportunity_overlays(opportunity))
        scene.headline = _headline(opportunity)

    # ---- priority 2 : the confluence
    for group in (confluences or [])[:1]:
        overlays.extend(_confluence_overlays(group))
        if not scene.headline:
            scene.headline = [
                f"CONFLUENCE {group.score:g}/{group.max_score:g} - {group.state}",
                f"Direction observee : {group.direction}",
            ]

    # ---- priority 3 : the detections behind the reading
    sources = [item for item in (detections or []) if detection_price(item) is not None]
    sources.sort(key=lambda item: (_bar_time(item) or 0, item.id), reverse=True)
    kept = sources[: params.overlays.max_sources]
    dropped["sources"] = max(0, len(sources) - len(kept))
    for detection in kept:
        overlay = _detection_overlay(detection)
        if overlay is not None:
            overlays.append(overlay)

    # ---- priority 4 : the context (the current trend, nothing else)
    context = _context_overlays(candles, detections or [])
    kept_context = context[: params.overlays.max_context]
    dropped["context"] = max(0, len(context) - len(kept_context))
    overlays.extend(kept_context)

    # ---- budget: zones then levels, never beyond what stays readable
    zones = [item for item in overlays if item.kind is OverlayKind.ZONE]
    levels = [item for item in overlays if item.kind is OverlayKind.LEVEL]
    markers = [item for item in overlays if item.kind is OverlayKind.MARKER]
    labels = [item for item in overlays if item.kind is OverlayKind.LABEL]
    if len(zones) > params.overlays.max_zones:
        dropped["zones"] = len(zones) - params.overlays.max_zones
        zones = zones[: params.overlays.max_zones]
    if len(levels) > params.overlays.max_levels:
        dropped["levels"] = len(levels) - params.overlays.max_levels
        levels = levels[: params.overlays.max_levels]

    scene.overlays = _dedupe_by_price([*labels, *markers, *zones, *levels], candles, dropped)
    total_dropped = sum(dropped.values())
    if total_dropped:
        scene.notes.append(
            "elements non dessines (budget de lisibilite) : "
            + ", ".join(f"{count} {name}" for name, count in dropped.items() if count)
        )
    logger.info(
        "Capture scene %s %s: %s candles, %s overlays (%s dropped)",
        series.symbol,
        timeframe_value,
        len(candles),
        len(scene.overlays),
        total_dropped,
    )
    return scene


def _dedupe_by_price(overlays: list[Overlay], candles: list, dropped: dict) -> list[Overlay]:
    """Keeps one label by price band.

    Six detections sitting on the same price all deserve to exist, but drawing six
    identical labels would be unreadable. The closest ones are dropped in favour of
    the most important (priority first), and the count is reported - the capture
    never pretends it showed everything.
    """
    if not candles:
        return overlays
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    span = max(highs) - min(lows)
    if span <= 0:
        return overlays
    band = span * 0.012
    kept: list[Overlay] = []
    too_close = 0
    for overlay in sorted(overlays, key=lambda item: item.priority):
        price = overlay.price
        if price is None and overlay.top is not None:
            price = (overlay.top + (overlay.bottom if overlay.bottom is not None else overlay.top)) / 2
        if price is None:
            kept.append(overlay)
            continue
        if any(
            other.price is not None and abs(other.price - price) < band
            for other in kept
            if other.kind is not OverlayKind.LABEL or overlay.kind is OverlayKind.LABEL
        ):
            too_close += 1
            continue
        kept.append(overlay)
    dropped["labels trop proches"] = too_close
    return kept


# ------------------------------------------------------------------ elements
def _opportunity_overlays(opportunity: Opportunity) -> list[Overlay]:
    out: list[Overlay] = []
    if opportunity.reference_price is not None:
        out.append(
            Overlay(
                kind=OverlayKind.LEVEL,
                priority=OverlayPriority.MAIN_EVENT.value,
                label=f"{opportunity.direction} - prix de reference",
                price=float(opportunity.reference_price),
                color=SOURCE_COLORS["OPPORTUNITY"],
                source="OPPORTUNITY",
                source_id=opportunity.id,
                direction=opportunity.direction,
                style="dashed",
            )
        )
    for level in opportunity.watch_levels[:2]:
        out.append(
            Overlay(
                kind=OverlayKind.LEVEL,
                priority=OverlayPriority.CONFLUENCE.value,
                label=level.label,
                price=float(level.price),
                color=SOURCE_COLORS["CONFLUENCE"],
                source="OPPORTUNITY",
                source_id=opportunity.id,
                style="dotted",
            )
        )
    return out


def _confluence_overlays(group: ConfluenceGroup) -> list[Overlay]:
    prices = [event.price for event in group.events if event.price is not None]
    out: list[Overlay] = []
    if prices:
        out.append(
            Overlay(
                kind=OverlayKind.ZONE,
                priority=OverlayPriority.CONFLUENCE.value,
                label=f"CONFLUENCE {group.score:g}/{group.max_score:g} ({group.direction})",
                bottom=min(prices),
                top=max(prices),
                color=SOURCE_COLORS["CONFLUENCE"],
                source="CONFLUENCE",
                source_id=group.id,
                direction=group.direction,
            )
        )
    label = f"{group.state} {group.score:g}/{group.max_score:g}"
    out.append(
        Overlay(
            kind=OverlayKind.LABEL,
            priority=OverlayPriority.CONFLUENCE.value,
            label=label,
            price=float(max(prices)) if prices else None,
            color=SOURCE_COLORS["CONFLUENCE"],
            source="CONFLUENCE",
            source_id=group.id,
        )
    )
    return out


def _detection_overlay(detection: PatternDetection) -> Overlay | None:
    """One drawable element per detection, named with the engine it comes from.

    The geometry comes from the detection's own drawing (its real levels and zones)
    and the price from the same helper the confluence normaliser uses, so the
    capture and the confluence can never disagree about a price.
    """
    price = detection_price(detection)
    if price is None:
        return None
    source = _source_name(detection)
    color = SOURCE_COLORS.get(source, "#9aa4b2")
    kind = _kind_for(detection.pattern)
    zone = _zone_bounds(detection)
    entry = {
        "kind": kind,
        "priority": OverlayPriority.SOURCE.value,
        "label": f"{_short(detection.pattern)} ({_source_short(source)})",
        "price": float(price),
        "time": _bar_time(detection),
        "color": color,
        "source": source,
        "source_id": detection.id,
        "direction": detection.direction.value,
        "style": "solid" if kind is not OverlayKind.MARKER else "dotted",
    }
    if zone is not None:
        entry["bottom"], entry["top"] = zone
    return Overlay(**entry)


def _zone_bounds(detection: PatternDetection) -> tuple[float, float] | None:
    """Real bounds of the first zone the detection publishes, if it publishes one."""
    for zone in detection.drawing.zones:
        if zone.price_top is None or zone.price_bottom is None:
            continue
        if abs(zone.price_top - zone.price_bottom) < 1e-12:
            continue
        return float(min(zone.price_bottom, zone.price_top)), float(max(zone.price_bottom, zone.price_top))
    return None


def _source_name(detection: PatternDetection) -> str:
    return detection.source_engine.value


def _source_short(source: str) -> str:
    from app.capture.renderer import SOURCE_SHORT

    return SOURCE_SHORT.get(source, source.title())


def _bar_time(detection: PatternDetection) -> int | None:
    if detection.detected_at_bar_time:
        return int(detection.detected_at_bar_time)
    if detection.coordinates:
        return int(detection.coordinates[-1].time)
    return int(detection.timestamp.timestamp())


def _kind_for(pattern: str) -> OverlayKind:
    upper = pattern.upper()
    if any(token in upper for token in ZONE_KINDS):
        return OverlayKind.ZONE
    if any(token in upper for token in MARKER_KINDS):
        return OverlayKind.MARKER
    if any(token in upper for token in LEVEL_KINDS):
        return OverlayKind.LEVEL
    return OverlayKind.LEVEL


def _short(pattern: str) -> str:
    text = pattern.replace("BEARISH_", "").replace("BULLISH_", "").replace("_", " ")
    return text.strip()[:26]


def _context_overlays(candles: list, detections: list[PatternDetection]) -> list[Overlay]:
    """Context = the trend observed by the structure engine, drawn as a band.

    The trend is read from the real structural detections (the last BOS/CHOCH/MSS
    of the series); when the engines published nothing, there IS no context and the
    capture simply shows none.
    """
    structural = [
        item
        for item in detections
        if item.pattern.upper().replace("BULLISH_", "").replace("BEARISH_", "") in LEVEL_KINDS
        and detection_price(item) is not None
    ]
    if not structural:
        return []
    structural.sort(key=lambda item: _bar_time(item) or 0, reverse=True)
    latest = structural[0]
    direction = latest.direction.value
    return [
        Overlay(
            kind=OverlayKind.LABEL,
            priority=OverlayPriority.CONTEXT.value,
            label=f"contexte structure : {direction} ({_short(latest.pattern)})",
            price=float(detection_price(latest)),
            color="#8892a4",
            source=_source_name(latest),
            source_id=latest.id,
            direction=direction,
        )
    ]


def _confluence_event_price(event) -> float | None:
    """The price of a confluence event, as carried by the Phase 5 normaliser."""
    return float(event.price) if event.price is not None else None


def _headline(opportunity: Opportunity) -> list[str]:
    lines = [
        f"{opportunity.direction} - {opportunity.state} - score {opportunity.score:g}/{opportunity.max_score:g}",
        f"Confluence {opportunity.confluence_state or '-'} ({opportunity.confluence_id or '-'})",
    ]
    if opportunity.no_trade_reason:
        lines.append(f"Refus : {opportunity.no_trade_reason}")
    elif opportunity.blocked_by:
        lines.append(f"Direction non nommee : {opportunity.blocked_by}")
    return lines
