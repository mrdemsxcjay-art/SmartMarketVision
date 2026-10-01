"""Internal engine types (pivots, trendlines, candidates).

These types never leave the backend: the API always exposes
:class:`app.schemas.events.PatternDetection`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas.market import Candle


@dataclass(frozen=True)
class Pivot:
    """A confirmed swing point."""

    index: int
    time: int
    price: float
    kind: str  # "HIGH" | "LOW"
    confirmed_at_index: int

    @property
    def is_high(self) -> bool:
        return self.kind == "HIGH"

    @property
    def iso(self) -> str:
        return datetime.fromtimestamp(self.time, tz=timezone.utc).isoformat()

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "timestamp": self.iso,
            "time": self.time,
            "price": self.price,
            "type": self.kind,
        }


@dataclass
class TrendLine:
    """Line fitted through pivots, expressed per bar and per second."""

    start_index: int
    end_index: int
    slope_per_bar: float
    intercept: float  # value at index 0
    kind: str  # "UPPER" | "LOWER" | "NECKLINE"
    pivots: list[Pivot] = field(default_factory=list)
    touches: int = 0
    r2: float = 0.0
    touch_indices: list[int] = field(default_factory=list)

    def value_at(self, index: int) -> float:
        return self.intercept + self.slope_per_bar * index

    def slope_per_second(self, timeframe_seconds: int) -> float:
        return self.slope_per_bar / max(1, timeframe_seconds)


@dataclass
class Candidate:
    """A formation found by a detector, before identity / lifecycle handling."""

    pattern: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    pivots: list[Pivot]
    evidence: list[str]
    evidence_points: dict[str, object]
    factors: list[tuple[str, bool, float, str]]  # criterion, passed, weight, detail
    parameters: dict[str, object]
    levels: dict[str, float] = field(default_factory=dict)
    lines: list[TrendLine] = field(default_factory=list)
    zones: list[dict[str, object]] = field(default_factory=list)
    #: levels whose break is watched, as (level_type, price, direction_of_that_break)
    breakout_levels: list[tuple[str, float, str]] = field(default_factory=list)
    invalidation_level: float | None = None
    invalidation_level_type: str | None = None
    invalidation_reason: str | None = None
    detected_at_bar_time: int | None = None
    #: bar index from which a breakout may be looked for (formation completion)
    watch_from_index: int | None = None
    #: bar index after which the formation is expired if nothing happened
    max_bars_to_confirm: int | None = None
    notes: list[str] = field(default_factory=list)
    #: extra bar times that identify the formation when it has no pivot of its own
    #: (the pole of a flag, for instance)
    extra_signature: list[int] = field(default_factory=list)
    #: identity of the **real level** the event is tied to, for the detectors that
    #: are emitted once per level of the chartist engine (Price Action ``REJECTION``
    #: and ``FAILED_BREAKOUT``). Two detections born of two different levels must
    #: never share an id, even when the same candle produces both. Built from real
    #: values only (published level id + price); left empty by every other detector,
    #: whose identity keeps using their pivot / extra signature.
    level_identity: str | None = None

    def pivot_signature(self) -> str:
        """Stable identity of the formation: the real bar times of its pivots."""
        times = [str(pivot.time) for pivot in self.pivots]
        times += [str(time) for time in sorted(self.extra_signature)]
        return ",".join(times)


@dataclass
class BarContext:
    """Everything the detectors need about one series."""

    symbol: str
    timeframe: str
    candles: list[Candle]  # closed candles only, oldest first
    digits: int
    pip_size: float
    atr: float
    pivots: list[Pivot]
    #: long ATR: the volatility scale used to size patterns
    atr_slow: float = 0.0

    @property
    def size_atr(self) -> float:
        """Reference volatility for size thresholds (falls back to the short ATR)."""
        return self.atr_slow if self.atr_slow > 0 else self.atr

    def index_of_time(self, time: int) -> int | None:
        for i, candle in enumerate(self.candles):
            if candle.time == time:
                return i
        return None

    @property
    def last_index(self) -> int:
        return len(self.candles) - 1

    @property
    def last_close(self) -> float:
        return self.candles[-1].close if self.candles else 0.0
