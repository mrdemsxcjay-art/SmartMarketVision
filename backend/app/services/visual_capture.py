"""Chart snapshot architecture (Phase 1: contract only, no rendering).

The goal for later phases: when a detector fires, produce an image of the chart
at the detection instant, containing candles, symbol, timeframe, timestamp,
price, levels, zones, annotations and the pattern name - then push it through
``TelegramNotifier.send_image()``.

PHASE 1 DELIBERATE LIMIT
------------------------
``capture()`` does NOT return an image and never fabricates one: it reports
``CAPTURE_NOT_IMPLEMENTED``. What is real today is ``build_context()``, which
assembles exactly the data the future renderer needs, from real series only.
No fake detection is created to make this module look used.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import DEFAULT_DATA_DIR
from app.logging_conf import get_logger
from app.schemas.events import PatternDetection
from app.schemas.market import Candle, Timeframe

logger = get_logger(__name__)

#: where future detection snapshots will be written (nothing is written in Phase 1)
SNAPSHOT_DIR = DEFAULT_DATA_DIR / "snapshots"


class CaptureStatus(str, Enum):
    NOT_IMPLEMENTED = "CAPTURE_NOT_IMPLEMENTED"
    READY = "CAPTURE_READY"
    FAILED = "CAPTURE_FAILED"


class SnapshotLevel(BaseModel):
    """Horizontal level (support, resistance, swing, order-block edge...)."""

    price: float
    label: str
    color: str | None = None
    style: str = "solid"
    kind: str = "LEVEL"


class SnapshotZone(BaseModel):
    """Price zone (order block, FVG, liquidity area...)."""

    top: float
    bottom: float
    label: str
    color: str | None = None
    kind: str = "ZONE"


class SnapshotAnnotation(BaseModel):
    """Free annotation: text, arrow, marker or trendline."""

    kind: str = "TEXT"  # TEXT | ARROW | MARKER | TRENDLINE | RECTANGLE
    label: str
    time: int | None = None
    price: float | None = None
    start: dict[str, float] | None = None
    end: dict[str, float] | None = None
    color: str | None = None


class SnapshotRequest(BaseModel):
    """Everything the future renderer needs. Built from real data only."""

    symbol: str
    timeframe: Timeframe
    candles: list[Candle] = Field(default_factory=list)
    price: float | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    title: str | None = None
    levels: list[SnapshotLevel] = Field(default_factory=list)
    zones: list[SnapshotZone] = Field(default_factory=list)
    annotations: list[SnapshotAnnotation] = Field(default_factory=list)
    pattern_name: str | None = None
    detection: PatternDetection | None = None


class SnapshotResult(BaseModel):
    status: CaptureStatus
    image_path: str | None = None
    image_base64: str | None = None
    context: dict | None = None
    reason: str | None = None


class ChartSnapshotService:
    """Renders/stores detection snapshots (rendering arrives in a later phase)."""

    def __init__(self, output_dir: Path | None = None, enabled: bool = False) -> None:
        self.output_dir = output_dir or SNAPSHOT_DIR
        self.enabled = enabled  # must stay False in Phase 1

    # ------------------------------------------------------------ context
    def build_context(self, request: SnapshotRequest) -> dict:
        """Assemble the render payload. Pure data, no rendering, no invention."""
        candles = sorted(request.candles, key=lambda c: c.time)
        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe.value,
            "timestamp": request.timestamp.isoformat(),
            "price": request.price if request.price is not None else (candles[-1].close if candles else None),
            "title": request.title or f"{request.symbol} {request.timeframe.value}",
            "candle_count": len(candles),
            "candles": [c.model_dump() for c in candles],
            "levels": [level.model_dump() for level in request.levels],
            "zones": [zone.model_dump() for zone in request.zones],
            "annotations": [annotation.model_dump() for annotation in request.annotations],
            "pattern_name": request.pattern_name,
            "detection_id": request.detection.id if request.detection else None,
            "direction": request.detection.direction.value if request.detection else None,
            "required_elements": [
                "candles",
                "symbol",
                "timeframe",
                "timestamp",
                "price",
                "levels",
                "zones",
                "annotations",
                "pattern_name",
            ],
            "renderer": {
                "implemented": False,
                "planned": "headless renderer over the same candle series used by the dashboard",
            },
        }

    # ------------------------------------------------------------ capture
    async def capture(self, request: SnapshotRequest) -> SnapshotResult:
        """Phase 1: never produces an image (and never a fake one)."""
        context = self.build_context(request)
        logger.info(
            "Snapshot requested for %s %s (%s candles) - renderer not implemented in Phase 1",
            request.symbol,
            request.timeframe.value,
            len(request.candles),
        )
        return SnapshotResult(
            status=CaptureStatus.NOT_IMPLEMENTED,
            context=context,
            reason=(
                "Chart rendering is scheduled for a later phase. Phase 1 only prepares "
                "the data contract; no placeholder or synthetic image is produced."
            ),
        )

    # ------------------------------------------------------------- helpers
    @staticmethod
    def to_base64(path: str | Path) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")

    def describe(self) -> dict:
        return {
            "implemented": False,
            "enabled": self.enabled,
            "status": "CAPTURE_NOT_IMPLEMENTED",
            "output_dir": str(self.output_dir),
            "required_elements": [
                "candles",
                "symbol",
                "timeframe",
                "timestamp",
                "price",
                "levels",
                "zones",
                "annotations",
                "pattern_name",
            ],
        }


snapshot_service = ChartSnapshotService()
