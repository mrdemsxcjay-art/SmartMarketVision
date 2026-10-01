"""Internal types of the SMC / ICT engine (Phase 4).

They never leave the backend: the API always exposes
:class:`app.schemas.events.PatternDetection` with ``category = SMC_ICT``, i.e.
the exact same contract the chartist and price-action engines already use. The
dashboard, the event bus and the SQLite repository therefore need no new shape.

Reuse policy (Phase 4 §1)
-------------------------
* pivots come from :func:`app.services.structure.find_swings` (Phase 1/2) - this
  module never re-implements a pivot detector;
* candle metrics come from :class:`app.price_action.candles.CandleMetrics`;
* ``ScanContext`` mirrors the price-action contract so every size threshold is
  ``max(pips floor, ATR share)`` and no magic number is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from app.price_action.candles import CandleMetrics, size_threshold
from app.schemas.structure import SwingKind, SwingPoint
from app.smc_ict.params import SmcIctParams


@dataclass(frozen=True)
class ScanContext:
    """Everything a detector needs about one series - measured once, reused."""

    symbol: str
    timeframe: str
    metrics: list[CandleMetrics]
    params: SmcIctParams
    atr: float
    pip_size: float
    digits: int = 5
    #: swings already confirmed on this window (Phase 1/2 pivot detector)
    swings: tuple["SmcSwing", ...] = ()

    def min_size(self, absolute_pips: float, atr_share: float) -> float:
        return size_threshold(absolute_pips, atr_share, self.pip_size, self.atr)

    def pips(self, price_distance: float) -> float:
        return abs(price_distance) / self.pip_size if self.pip_size else 0.0

    def atr_multiple(self, price_distance: float) -> float:
        return abs(price_distance) / self.atr if self.atr else 0.0

    def index_of_time(self, time_value: int) -> int | None:
        for i, bar in enumerate(self.metrics):
            if bar.time == time_value:
                return i
        return None

    def bar_at(self, index: int) -> CandleMetrics | None:
        if 0 <= index < len(self.metrics):
            return self.metrics[index]
        return None


@dataclass(frozen=True)
class SmcSwing:
    """A confirmed swing with a MEASURABLE strength.

    ``strength`` is an integer, reproducible from the OHLC:
      * +1 per extra bar, on each side, that the pivot dominates within
        ``dominance_bars`` (a swing that stands out over 4 bars is stronger than
        one that barely exceeds its 2 neighbours);
      * +1 per ``atr_scale`` ATR by which the pivot exceeds the highest high (or
        lowest low) of its own dominance window.

    A flat market therefore yields ``strength = 0``; nothing is estimated.
    """

    index: int
    time: int
    price: float
    kind: SwingKind
    strength: int
    confirmed_at_index: int
    dominance_left: int = 0
    dominance_right: int = 0
    prominence: float = 0.0

    @property
    def is_high(self) -> bool:
        return self.kind is SwingKind.HIGH

    @property
    def type_label(self) -> str:
        return "SWING_HIGH" if self.is_high else "SWING_LOW"

    @property
    def iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(self.time, tz=timezone.utc).isoformat()

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.iso,
            "time": self.time,
            "index": self.index,
            "price": self.price,
            "type": self.type_label,
            "strength": self.strength,
            "confirmed_at_index": self.confirmed_at_index,
            "dominance_left": self.dominance_left,
            "dominance_right": self.dominance_right,
            "prominence": round(self.prominence, 6),
        }


@dataclass
class SmcCandidate:
    """A detection produced by a detector, before it becomes an API detection."""

    pattern: str                       # BOS, CHOCH, MSS, EQUAL_HIGH, ...
    direction: str                     # BULLISH | BEARISH | NEUTRAL
    index: int                         # bar index of the triggering candle
    time: int                          # bar open time (epoch seconds)
    #: (label, satisfied, weight, detail) - the "why" behind every candidate
    criteria: list[tuple[str, bool, float, str]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    measurements: dict[str, object] = field(default_factory=dict)
    levels: dict[str, float] = field(default_factory=dict)
    zones: list[dict[str, object]] = field(default_factory=list)
    markers: list[dict[str, object]] = field(default_factory=list)
    coordinates: list[tuple[int, float, str, str]] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)
    #: index of the very first bar the detection is anchored on (dedup + drawing)
    source_from_index: int | None = None
    #: label used in confluence / lifecycle, e.g. "ORDER_BLOCK"
    family: str = "STRUCTURE"


#: SMC/ICT families
STRUCTURAL = frozenset({"BOS", "CHOCH", "MSS"})
LIQUIDITY = frozenset({"EQUAL_HIGH", "EQUAL_LOW", "LIQUIDITY_POOL_ESTIMATE", "LIQUIDITY_SWEEP"})
GAPS = frozenset({"BULLISH_FVG", "BEARISH_FVG"})
BLOCKS = frozenset({"BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK", "BREAKER_BLOCK"})
RANGE = frozenset({"DISPLACEMENT", "DEALING_RANGE", "PREMIUM", "DISCOUNT"})

ALL_PATTERNS = STRUCTURAL | LIQUIDITY | GAPS | BLOCKS | RANGE


def as_json(value):
    """Recursively convert dataclasses / enums to plain JSON-safe values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): as_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [as_json(v) for v in value]
    if is_dataclass(value):
        return {f.name: as_json(getattr(value, f.name)) for f in fields(value)}
    if hasattr(value, "value") and hasattr(value, "name"):  # Enum
        return value.value
    if hasattr(value, "as_dict"):
        return as_json(value.as_dict())
    return str(value)


__all__ = [
    "ScanContext",
    "SmcSwing",
    "SmcCandidate",
    "SwingPoint",
    "SwingKind",
    "ALL_PATTERNS",
    "STRUCTURAL",
    "LIQUIDITY",
    "GAPS",
    "BLOCKS",
    "RANGE",
    "as_json",
]
