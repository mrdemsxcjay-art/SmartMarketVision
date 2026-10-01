"""Builds the drawing specification from a detection.

The backend owns the geometry: the dashboard only renders what it receives, so a
detection always looks the same everywhere and the drawing can be unit-tested.
"""

from __future__ import annotations

from app.patterns.models import Candidate
from app.schemas.events import (
    DrawingLevel,
    DrawingLine,
    DrawingMarker,
    DrawingSpec,
    DrawingZone,
    PatternCoordinate,
)


def _value(pivot, field: str):
    """Read a pivot field from either a Pivot object or its JSON dict form.

    Detectors hand ``evidence_points`` to the API as plain dicts (JSON-safe) but
    the drawing code also needs to read them; both shapes are accepted here.
    """
    if isinstance(pivot, dict):
        if field == "is_high":
            kind = str(pivot.get("type") or pivot.get("kind") or "")
            return kind.upper().startswith("H")
        if field == "iso":
            return pivot.get("iso")
        return pivot.get(field)
    return getattr(pivot, field)


def _point(pivot, role: str, label: str | None = None) -> PatternCoordinate:
    return PatternCoordinate(
        time=_value(pivot, "time"), price=_value(pivot, "price"), role=role, label=label or role
    )


def build(candidate: Candidate, context) -> tuple[DrawingSpec, list[PatternCoordinate]]:
    """Return (drawing spec, coordinates) for a candidate."""
    levels: list[DrawingLevel] = []
    lines: list[DrawingLine] = []
    zones: list[DrawingZone] = []
    markers: list[DrawingMarker] = []
    coordinates: list[PatternCoordinate] = []

    roles = dict(candidate.evidence_points.get("roles", {}) or {})
    for role, pivot in (candidate.evidence_points.get("pivots", {}) or {}).items():
        coordinates.append(_point(pivot, role))

    # ------------------------------------------------------------- markers
    for role, pivot in (candidate.evidence_points.get("pivots", {}) or {}).items():
        label = roles.get(role, role)
        markers.append(
            DrawingMarker(
                time=_value(pivot, "time"),
                price=_value(pivot, "price"),
                position="aboveBar" if _value(pivot, "is_high") else "belowBar",
                shape="circle",
                label=label,
                kind=str(_value(pivot, "kind") or _value(pivot, "type") or ""),
            )
        )

    # -------------------------------------------------------------- levels
    for name, price in candidate.levels.items():
        levels.append(
            DrawingLevel(
                price=price,
                label=name,
                kind=_level_kind(name),
            )
        )

    # --------------------------------------------------------------- lines
    # The endpoints of a *fitted* line are geometry, not observations: they are
    # carried by ``drawing.lines`` (used to render the trendline) and never by
    # ``coordinates``, which must stay auditable against real bars.
    for line in candidate.lines:
        points = [
            PatternCoordinate(
                time=_time_at(context, line.start_index),
                price=line.value_at(line.start_index),
                role=line.kind,
                label=line.kind,
            ),
            PatternCoordinate(
                time=_time_at(context, line.end_index),
                price=line.value_at(line.end_index),
                role=line.kind,
                label=line.kind,
            ),
        ]
        lines.append(DrawingLine(kind=line.kind, label=line.kind, points=points))

    # --------------------------------------------------------------- zones
    for zone in candidate.zones:
        zones.append(
            DrawingZone(
                time_start=int(zone["time_start"]),
                time_end=int(zone["time_end"]),
                price_top=float(zone["price_top"]),
                price_bottom=float(zone["price_bottom"]),
                label=str(zone.get("label", "ZONE")),
                kind=str(zone.get("kind", "CONSOLIDATION")),
            )
        )

    spec = DrawingSpec(levels=levels, lines=lines, zones=zones, markers=markers)
    return spec, coordinates


def _time_at(context, index: int) -> int:
    if not context.candles:
        return 0
    index = max(0, min(index, len(context.candles) - 1))
    return context.candles[index].time


def _level_kind(name: str) -> str:
    upper = name.upper()
    for keyword in ("NECKLINE", "SUPPORT", "RESISTANCE", "TRENDLINE", "CHANNEL", "BREAKOUT", "POLE", "APEX"):
        if keyword in upper:
            return keyword
    return "LEVEL"
