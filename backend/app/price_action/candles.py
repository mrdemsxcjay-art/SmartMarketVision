"""Candle measurements - the raw material of every price-action rule.

Nothing here decides anything: this module only measures a candle from its real
OHLC, so the detectors (and the dashboard, and the tests) reason on the same
numbers. All ratios are defined for a zero range (they return 0.0) so no rule can
divide by zero or produce a NaN.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.market import Candle


@dataclass(frozen=True)
class CandleMetrics:
    """Objective geometry of one real candle."""

    index: int
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    #: |close - open|
    body_size: float
    #: high - low
    range: float
    #: high - max(open, close)
    upper_wick: float
    #: min(open, close) - low
    lower_wick: float

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_ratio(self) -> float:
        """body / range (0 for a zero-range candle)."""
        return self.body_size / self.range if self.range > 0 else 0.0

    @property
    def upper_wick_ratio(self) -> float:
        return self.upper_wick / self.range if self.range > 0 else 0.0

    @property
    def lower_wick_ratio(self) -> float:
        return self.lower_wick / self.range if self.range > 0 else 0.0

    @property
    def dominant_wick(self) -> float:
        return max(self.upper_wick, self.lower_wick)

    @property
    def dominant_side(self) -> str:
        """UPPER | LOWER | NONE - where the long wick is."""
        if self.upper_wick <= 0 and self.lower_wick <= 0:
            return "NONE"
        if abs(self.upper_wick - self.lower_wick) <= 1e-12:
            return "NONE"
        return "UPPER" if self.upper_wick > self.lower_wick else "LOWER"

    @property
    def opposite_wick(self) -> float:
        """The wick on the other side of the body than :attr:`dominant_side`."""
        return self.upper_wick if self.dominant_side == "LOWER" else self.lower_wick

    @property
    def opposite_wick_ratio(self) -> float:
        return self.opposite_wick / self.range if self.range > 0 else 0.0

    @property
    def wick_to_body(self) -> float:
        """Dominant wick / body. ``inf`` when the body is empty and a wick exists."""
        if self.body_size > 0:
            return self.dominant_wick / self.body_size
        return float("inf") if self.dominant_wick > 0 else 0.0

    @property
    def close_position(self) -> float:
        """0 = close on the low, 1 = close on the high."""
        return (self.close - self.low) / self.range if self.range > 0 else 0.5

    @property
    def body_top(self) -> float:
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        return min(self.open, self.close)

    def as_dict(self) -> dict[str, object]:
        """JSON-safe view exposed in ``evidence_points`` and in the API."""
        return {
            "candle_index": self.index,
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "body_size": round(self.body_size, 10),
            "upper_wick": round(self.upper_wick, 10),
            "lower_wick": round(self.lower_wick, 10),
            "range": round(self.range, 10),
            "body_ratio": round(self.body_ratio, 4),
            "wick_ratios": {
                "upper": round(self.upper_wick_ratio, 4),
                "lower": round(self.lower_wick_ratio, 4),
                "dominant": round(self.dominant_wick / self.range, 4) if self.range > 0 else 0.0,
                "opposite": round(self.opposite_wick_ratio, 4),
                "wick_to_body": round(self.wick_to_body, 4) if self.wick_to_body != float("inf") else None,
            },
            "close_position": round(self.close_position, 4),
            "direction": "BULLISH" if self.bullish else ("BEARISH" if self.bearish else "NEUTRAL"),
        }


def measure(candle: Candle, index: int) -> CandleMetrics:
    """Build the metrics of one real candle (no estimation, no smoothing)."""
    return CandleMetrics(
        index=index,
        time=candle.time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        body_size=abs(candle.close - candle.open),
        range=candle.high - candle.low,
        upper_wick=candle.high - max(candle.open, candle.close),
        lower_wick=min(candle.open, candle.close) - candle.low,
    )


def measure_all(candles: list[Candle]) -> list[CandleMetrics]:
    return [measure(candle, index) for index, candle in enumerate(candles)]


#: relative tolerance used for the *boundary* comparisons of a rule. It is ~1e-9,
#: i.e. far below any market reality: its only job is to stop binary rounding
#: (0.0018/0.0020 = 0.9000000000000001) from deciding whether a rule applies.
RELATIVE_EPSILON = 1e-9


def ge(value: float, threshold: float) -> bool:
    """``value >= threshold``, immune to binary rounding."""
    return value >= threshold - abs(threshold) * RELATIVE_EPSILON - 1e-12


def le(value: float, threshold: float) -> bool:
    """``value <= threshold``, immune to binary rounding."""
    return value <= threshold + abs(threshold) * RELATIVE_EPSILON + 1e-12


def gt(value: float, threshold: float) -> bool:
    return value > threshold + abs(threshold) * RELATIVE_EPSILON + 1e-12


def lt(value: float, threshold: float) -> bool:
    return value < threshold - abs(threshold) * RELATIVE_EPSILON - 1e-12


def pips(price_delta: float, pip_size: float) -> float:
    """Convert a price difference into pips (the unit a human re-checks)."""
    return price_delta / pip_size if pip_size else 0.0


def size_threshold(absolute_pips: float, atr_share: float, pip_size: float, atr: float) -> float:
    """max(absolute floor in pips, ATR fraction) - one volatility scale per symbol."""
    return max(absolute_pips * pip_size, atr_share * atr)
