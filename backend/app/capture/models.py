"""Capture data models (Phase 7).

A capture is a PNG of the **real** chart at the instant of a reading, plus the
metadata that makes it traceable (7.4). Every price, level and zone in a capture
comes from a candle or a detection: the renderer has no way to invent one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.market import Candle


class OverlayPriority(int, Enum):
    """7.2 - what is worth drawing, in order."""

    MAIN_EVENT = 1  # the opportunity being alerted
    CONFLUENCE = 2  # the confluence that carries it
    SOURCE = 3  # the detections behind the confluence
    CONTEXT = 4  # trend, dealing range, structure


class OverlayKind(str, Enum):
    ZONE = "ZONE"
    LEVEL = "LEVEL"
    MARKER = "MARKER"
    LABEL = "LABEL"


class Overlay(BaseModel):
    """One drawable element, traced back to its source id."""

    kind: OverlayKind
    priority: int = OverlayPriority.SOURCE.value
    label: str
    #: price geometry (a level uses ``price``; a zone uses ``bottom``/``top``)
    price: float | None = None
    bottom: float | None = None
    top: float | None = None
    #: bar time the element refers to (markers), real value from the data
    time: int | None = None
    color: str | None = None
    source: str = ""
    source_id: str | None = None
    direction: str | None = None
    style: str = "solid"


class CaptureScene(BaseModel):
    """Everything the renderer needs - all of it coming from the data."""

    symbol: str
    timeframe: str
    candles: list[Candle] = Field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    price: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    overlays: list[Overlay] = Field(default_factory=list)
    footer: str = ""
    #: free lines shown in the header band (confluence score, state, reasons...)
    headline: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def price_window(self) -> tuple[float, float]:
        """Real window covered by candles and overlays, with a small margin."""
        values: list[float] = []
        for candle in self.candles:
            values.extend([candle.high, candle.low])
        for overlay in self.overlays:
            if overlay.price is not None:
                values.append(overlay.price)
            if overlay.bottom is not None:
                values.append(overlay.bottom)
            if overlay.top is not None:
                values.append(overlay.top)
        if not values:
            return 0.0, 1.0
        low, high = min(values), max(values)
        if high - low < 1e-12:
            return low - 1e-5, high + 1e-5
        padding = (high - low) * 0.06
        return low - padding, high + padding

    def overlays_by_priority(self) -> list[Overlay]:
        return sorted(self.overlays, key=lambda item: (item.priority, item.label))


class CaptureMetadata(BaseModel):
    """7.4 - the identity of a capture, stored with it."""

    capture_id: str
    opportunity_id: str | None = None
    confluence_id: str | None = None
    symbol: str
    timeframe: str
    timestamp: datetime
    path: str
    hash: str
    width: int
    height: int
    resolution: str
    bytes: int
    overlay_count: int = 0
    tier: str = "phone"
    dedup_key: str | None = None
    generation: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")


class CaptureResult(BaseModel):
    status: str
    metadata: CaptureMetadata | None = None
    scene: CaptureScene | None = None
    reason: str | None = None
    reused: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "CAPTURE_READY"
