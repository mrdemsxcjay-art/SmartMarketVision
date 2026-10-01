"""Generic event + detection models.

``MarketEvent`` is the envelope shared by REST, WebSocket and SSE.

``PatternDetection`` is the detection contract:
* Phase 1 created it and never produced an instance;
* Phase 2 (chartist engine) fills it for CHARTISTE detections only - every field
  is derived from real OHLC, the parameters used and explicit criteria;
* PRICE_ACTION and SMC_ICT stay unimplemented.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.market import Timeframe


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class EventType(str, Enum):
    MARKET_UPDATE = "MARKET_UPDATE"          # tick / quote refresh
    CANDLE_UPDATE = "CANDLE_UPDATE"          # forming candle changed
    CANDLE_CLOSED = "CANDLE_CLOSED"          # a bar just closed
    STRUCTURE_UPDATE = "STRUCTURE_UPDATE"    # swing/trend recomputed
    PROVIDER_STATUS = "PROVIDER_STATUS"      # provider reachable / down
    SYSTEM_STATUS = "SYSTEM_STATUS"          # scanner / stream state
    STREAM_HELLO = "STREAM_HELLO"
    #: sent to a single connection on connect: the current chartist state, so a
    #: reconnecting dashboard never has to wait for the next detection
    DETECTIONS_SNAPSHOT = "DETECTIONS_SNAPSHOT"
    #: same idea for the Phase 3 engine: sent to one connection on connect so a
    #: reloading dashboard shows the current price-action state immediately
    PRICE_ACTION_SNAPSHOT = "PRICE_ACTION_SNAPSHOT"
    # Phase 2 - chart pattern lifecycle (three distinct, never merged states)
    PATTERN_DETECTED = "PATTERN_DETECTED"          # formation completed, not yet broken
    PATTERN_CONFIRMED = "PATTERN_CONFIRMED"        # breakout validated the formation
    PATTERN_INVALIDATED = "PATTERN_INVALIDATED"    # structure broken the other way
    PATTERN_EXPIRED = "PATTERN_EXPIRED"            # too old / apex passed, dropped
    # Breakout and retest are separate events, never merged into the pattern
    BREAKOUT_DETECTED = "BREAKOUT_DETECTED"
    RETEST_DETECTED = "RETEST_DETECTED"
    # Phase 3 - price-action lifecycle, published on the same event bus
    PRICE_ACTION_DETECTED = "PRICE_ACTION_DETECTED"        # pattern or structure observed
    PRICE_ACTION_CONFIRMED = "PRICE_ACTION_CONFIRMED"      # a close cleared the trigger level
    PRICE_ACTION_INVALIDATED = "PRICE_ACTION_INVALIDATED"  # a close broke the other side
    PRICE_ACTION_EXPIRED = "PRICE_ACTION_EXPIRED"          # window elapsed / state over
    #: distinct event: a Phase 2 breakout was not held (level, breakout candle,
    #: failure candle, return price) - never merged into the breakout itself
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    # Phase 4 - SMC/ICT lifecycle, published on the SAME bus as phases 1-3
    SMC_DETECTED = "SMC_DETECTED"              # a new SMC object exists
    SMC_CONFIRMED = "SMC_CONFIRMED"            # its structural condition is met
    SMC_MITIGATED = "SMC_MITIGATED"            # price mitigated the zone/gap
    SMC_INVALIDATED = "SMC_INVALIDATED"        # price closed through it
    SMC_FILLED = "SMC_FILLED"                  # the band was traversed entirely
    SMC_EXPIRED = "SMC_EXPIRED"                # window elapsed / object dropped
    #: sent to a single connection on connect: the current SMC/ICT state
    SMC_ICT_SNAPSHOT = "SMC_ICT_SNAPSHOT"
    # Phase 5 - confluence lifecycle, published on the SAME bus as phases 1-4.
    #: several independent readings agree (WATCH / CONFLUENCE / STRONG_CONFLUENCE)
    CONFLUENCE_DETECTED = "CONFLUENCE_DETECTED"
    #: an existing confluence changed state (score or agreement moved)
    CONFLUENCE_UPDATED = "CONFLUENCE_UPDATED"
    #: distinct event: the readings contradict each other, shown as such
    CONFLUENCE_CONTRADICTED = "CONFLUENCE_CONTRADICTED"
    #: the window elapsed without a fresh reading
    CONFLUENCE_EXPIRED = "CONFLUENCE_EXPIRED"
    #: sent to a single connection on connect: the current confluence state
    CONFLUENCE_SNAPSHOT = "CONFLUENCE_SNAPSHOT"
    # Phase 6 - analytical opportunity lifecycle (never an order)
    OPPORTUNITY_CREATED = "OPPORTUNITY_CREATED"
    OPPORTUNITY_CONFIRMED = "OPPORTUNITY_CONFIRMED"
    OPPORTUNITY_WEAKENED = "OPPORTUNITY_WEAKENED"
    OPPORTUNITY_INVALIDATED = "OPPORTUNITY_INVALIDATED"
    OPPORTUNITY_EXPIRED = "OPPORTUNITY_EXPIRED"
    #: sent to a single connection on connect: the current opportunity state
    OPPORTUNITY_SNAPSHOT = "OPPORTUNITY_SNAPSHOT"
    # Phase 7/8 - capture + notification lifecycle (observability of the chain)
    CAPTURE_READY = "CAPTURE_READY"
    ALERT_QUEUED = "ALERT_QUEUED"
    ALERT_SENT = "ALERT_SENT"
    ALERT_FAILED = "ALERT_FAILED"


class MarketEvent(BaseModel):
    """Generic event envelope shared by REST, WebSocket and SSE."""

    id: str = Field(default_factory=lambda: new_id("evt"))
    symbol: str | None = None
    timeframe: Timeframe | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: EventType
    price: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "SCANNER"


class DetectionCategory(str, Enum):
    CHARTISTE = "CHARTISTE"
    PRICE_ACTION = "PRICE_ACTION"
    SMC_ICT = "SMC_ICT"


class DetectionDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class DetectionStatus(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    # Phase 4 - SMC/ICT lifecycle statuses (§20). They are additive: the
    # chartist and price-action engines keep using the four above.
    ACTIVE = "ACTIVE"              # a level/zone stands, nothing to confirm
    MITIGATED = "MITIGATED"        # price entered the zone without filling it
    FILLED = "FILLED"              # a fair value gap was traversed entirely


class DetectionSource(str, Enum):
    """Which detector produced the pattern - all unset in Phase 1."""

    NONE = "NONE"
    CHART_PATTERN_ENGINE = "CHART_PATTERN_ENGINE"
    PRICE_ACTION_ENGINE = "PRICE_ACTION_ENGINE"
    SMC_ICT_ENGINE = "SMC_ICT_ENGINE"


class PatternCoordinate(BaseModel):
    """One drawable point of a detection (real bar time + real price)."""

    time: int = Field(description="Bar open time, UTC epoch seconds")
    price: float
    role: str = Field(description="PEAK_1, PEAK_2, VALLEY, HEAD, NECKLINE_START, ...")
    label: str | None = None


class ConfidenceFactor(BaseModel):
    """One explicit, measurable criterion used in the confidence score."""

    criterion: str
    passed: bool
    weight: float
    detail: str


class ConfirmationInfo(BaseModel):
    """How (and whether) the formation was validated by price."""

    confirmed: bool = False
    level: float | None = Field(default=None, description="Level that had to be broken")
    level_type: str | None = Field(default=None, description="NECKLINE, TRENDLINE, SUPPORT, RESISTANCE...")
    breakout_time: int | None = None
    breakout_price: float | None = None
    breakout_candle_time: int | None = None
    candles_to_confirm: int | None = None
    volume: float | None = Field(default=None, description="Real volume when available, else null")
    note: str | None = None


class InvalidationInfo(BaseModel):
    """What would prove the detection wrong (and whether it already happened)."""

    invalidated: bool = False
    level: float | None = None
    level_type: str | None = None
    reason: str | None = None
    invalidated_at: int | None = None


class WatchedLevel(BaseModel):
    """A level whose break confirms (or invalidates) the formation.

    Stored with the detection so the engine has no hidden state: the same payload
    can be replayed later and produce the same lifecycle decisions.
    """

    level_type: str
    price: float
    direction: DetectionDirection = Field(description="Direction of the break that confirms")
    role: str = Field(default="CONFIRMATION", description="CONFIRMATION | INVALIDATION")


class BreakoutInfo(BaseModel):
    """Standalone breakout event - kept separate from the pattern itself."""

    id: str = Field(default_factory=lambda: new_id("brk"))
    parent_detection_id: str | None = None
    level: float
    level_type: str
    direction: DetectionDirection
    breakout_price: float
    breakout_time: int
    confirming_candle_time: int
    candles_to_breakout: int
    buffer_pips: float
    volume: float | None = None
    retested: bool = False


class RetestInfo(BaseModel):
    """Return move to a broken level, after a confirmed breakout only."""

    breakout_level: float
    breakout_candle_time: int
    retest_candle_time: int
    retest_price: float
    distance_to_level_pips: float
    confirmed: bool = False
    confirmation_candle_time: int | None = None
    candles_after_breakout: int = 0


class DrawingLevel(BaseModel):
    price: float
    label: str
    kind: str = "NECKLINE"


class DrawingLine(BaseModel):
    """Polyline through real detection points (trendline, neckline, channel)."""

    kind: str
    label: str
    points: list[PatternCoordinate] = Field(default_factory=list)


class DrawingZone(BaseModel):
    time_start: int
    time_end: int
    price_top: float
    price_bottom: float
    label: str
    kind: str = "CONSOLIDATION"


class DrawingMarker(BaseModel):
    time: int
    price: float
    position: str = Field(default="aboveBar", description="aboveBar | belowBar | inBar")
    shape: str = Field(default="circle", description="circle | square | arrowUp | arrowDown")
    label: str | None = None
    kind: str = "PIVOT"


class DrawingSpec(BaseModel):
    """Everything the dashboard needs to draw the detection - no client-side maths."""

    levels: list[DrawingLevel] = Field(default_factory=list)
    lines: list[DrawingLine] = Field(default_factory=list)
    zones: list[DrawingZone] = Field(default_factory=list)
    markers: list[DrawingMarker] = Field(default_factory=list)


class PatternDetection(BaseModel):
    """A chartist detection.

    Every field is derived from real OHLC and the detection parameters:
    * ``evidence`` is the human-readable justification checklist;
    * ``evidence_points`` holds the exact pivots used;
    * ``coordinates`` are the drawable points;
    * ``parameters`` are the thresholds actually used (reproducibility);
    * ``confidence`` is computed from explicit criteria only (never guessed).
    """

    id: str = Field(default_factory=lambda: new_id("det"))
    dedup_key: str | None = Field(
        default=None, description="Stable identity of the formation across its lifecycle"
    )
    symbol: str
    timeframe: Timeframe
    timestamp: datetime = Field(default_factory=utcnow)
    category: DetectionCategory = DetectionCategory.CHARTISTE
    pattern: str
    direction: DetectionDirection
    confidence: float | None = Field(default=None, description="0-100, weighted explicit criteria")
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    evidence_points: dict[str, Any] = Field(default_factory=dict)
    coordinates: list[PatternCoordinate] = Field(default_factory=list)
    drawing: DrawingSpec = Field(default_factory=DrawingSpec)
    parameters: dict[str, Any] = Field(default_factory=dict)
    confirmation: ConfirmationInfo = Field(default_factory=ConfirmationInfo)
    invalidation: InvalidationInfo = Field(default_factory=InvalidationInfo)
    breakout: BreakoutInfo | None = None
    retest: RetestInfo | None = None
    watch_levels: list[WatchedLevel] = Field(
        default_factory=list, description="Levels monitored after the formation completed"
    )
    status: DetectionStatus = DetectionStatus.DETECTED
    source_engine: DetectionSource = DetectionSource.CHART_PATTERN_ENGINE
    parent_detection_id: str | None = None
    detected_at_bar_time: int | None = Field(default=None, description="Bar that completed the formation")
    first_seen_at: datetime | None = None
    last_updated_at: datetime | None = None
    bars_in_window: int | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status in (DetectionStatus.DETECTED,)

    def signature(self) -> str:
        """Stable identity: symbol + timeframe + pattern + the pivots used."""
        if self.dedup_key:
            return self.dedup_key
        pivots = ",".join(str(p.time) for p in self.coordinates[:6])
        return f"{self.symbol}|{self.timeframe.value}|{self.pattern}|{pivots}"


class DetectorStatus(str, Enum):
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class DetectionsResponse(BaseModel):
    """Active detections for the requested scope."""

    status: str = "NO ACTIVE DETECTION"
    detections: list[PatternDetection] = Field(default_factory=list)
    engines: dict[str, DetectorStatus] = Field(default_factory=dict)
    message: str = (
        "Chartist (Phase 2) and price-action (Phase 3) engines detect formations from real "
        "closed OHLC. SMC/ICT is not implemented, no order is ever placed: this is an "
        "observation scanner."
    )
    counts: dict[str, int] = Field(default_factory=dict)
    #: engine counters (runs, bars analysed, last duration, persisted rows)
    stats: dict = Field(default_factory=dict)
