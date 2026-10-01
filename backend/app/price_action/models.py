"""Internal types of the price-action engine.

They never leave the backend: the API always exposes
:class:`app.schemas.events.PatternDetection` (category ``PRICE_ACTION``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.price_action.candles import CandleMetrics, size_threshold
from app.price_action.params import PriceActionParams


@dataclass(frozen=True)
class ScanContext:
    """Everything a detector needs about one series - measured once, reused.

    ``atr`` is the structural volatility scale (slow ATR when available): every
    size threshold is expressed as ``max(pips floor, ATR share)`` so the same
    parameter set works on EURUSD M15 and on USDJPY D1 without magic numbers.
    """

    symbol: str
    timeframe: str
    metrics: list[CandleMetrics]
    params: PriceActionParams
    atr: float
    pip_size: float
    digits: int = 5

    @property
    def candles(self) -> list[CandleMetrics]:
        return self.metrics

    def min_size(self, absolute_pips: float, atr_share: float) -> float:
        return size_threshold(absolute_pips, atr_share, self.pip_size, self.atr)


@dataclass(frozen=True)
class LevelRef:
    """A real level, taken from the chartist engine (never re-invented here).

    ``source`` keeps the origin so the evidence can say *where* the level comes
    from: a resistance cluster, a rectangle edge, a channel boundary, ...
    """

    price: float
    kind: str  # SUPPORT | RESISTANCE | RECTANGLE_EDGE | CHANNEL | BREAKOUT
    source: str  # e.g. "RESISTANCE ct_ab12..." / "RECTANGLE"
    source_id: str | None = None
    tolerance: float = 0.0
    last_touch_time: int | None = None
    age_bars: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "price": self.price,
            "kind": self.kind,
            "source": self.source,
            "source_id": self.source_id,
            "last_touch_time": self.last_touch_time,
            "age_bars": self.age_bars,
        }


@dataclass(frozen=True)
class BreakoutRef:
    """A confirmed breakout produced by the Phase 2 mechanism (chartist engine).

    The price-action engine never recomputes a breakout: it consumes this
    reference to detect a rejection of the break (``FAILED_BREAKOUT``) and the
    retest context.
    """

    level: float
    level_type: str
    direction: str  # BULLISH | BEARISH (direction of the break)
    breakout_time: int
    breakout_price: float
    parent_pattern: str
    parent_id: str
    retested: bool = False
    retest_time: int | None = None
    retest_price: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "level_type": self.level_type,
            "direction": self.direction,
            "breakout_time": self.breakout_time,
            "breakout_price": self.breakout_price,
            "parent_pattern": self.parent_pattern,
            "parent_id": self.parent_id,
            "retested": self.retested,
            "retest_time": self.retest_time,
            "retest_price": self.retest_price,
        }


@dataclass
class ConfluenceGroup:
    """Informative grouping of the three engines for one series.

    There is deliberately **no score and no signal** here: the group only says
    which structure, price-action and chartist elements coexist at the same time
    on the same instrument, so a human can read the context.
    """

    symbol: str
    timeframe: str
    chartist: list[dict[str, object]] = field(default_factory=list)
    price_action: list[dict[str, object]] = field(default_factory=list)
    structure: list[dict[str, object]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "groups": {
                "chartist": self.chartist,
                "price_action": self.price_action,
                "structure": self.structure,
            },
            "labels": self.labels,
            "trading_signal": False,
            "note": (
                "Confluence informative uniquement : aucune recommandation, aucun ordre, "
                "aucun signal d'entree. SMART MARKET VISION est un scanner d'observation."
            ),
        }


#: patterns produced by the structural part of the engine (context, not candlesticks)
STRUCTURAL_PATTERNS = frozenset({"IMPULSION", "CONSOLIDATION", "REJECTION", "FAILED_BREAKOUT"})

#: every pattern the engine can produce
ALL_PATTERNS = frozenset(
    {
        "BULLISH_ENGULFING",
        "BEARISH_ENGULFING",
        "BULLISH_PIN_BAR",
        "BEARISH_PIN_BAR",
        "HAMMER",
        "SHOOTING_STAR",
        "INSIDE_BAR",
        "OUTSIDE_BAR",
        "DOJI",
    }
) | STRUCTURAL_PATTERNS
