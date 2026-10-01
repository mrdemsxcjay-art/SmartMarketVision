"""Market data schemas (real OHLCV only - never synthetic in production)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Timeframe(str, Enum):
    """Supported timeframes. Values are the API/UI codes."""

    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def seconds(self) -> int:
        return {
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }[self.value]

    @property
    def label(self) -> str:
        return {
            "M5": "5 minutes",
            "M15": "15 minutes",
            "H1": "1 hour",
            "H4": "4 heures",
            "D1": "Journalier",
        }[self.value]


def as_timeframe(value: "Timeframe | str") -> Timeframe:
    """Normalise any timeframe input (enum or string) to a :class:`Timeframe`.

    ``str(Timeframe.M15)`` returns ``"Timeframe.M15"`` on Python 3.11+, so the
    enum instance is handled explicitly here instead of via ``str()``.
    """
    if isinstance(value, Timeframe):
        return value
    try:
        return Timeframe(str(value).strip().upper())
    except ValueError as exc:
        raise ValueError(f"unsupported timeframe '{value}'") from exc


class DataState(str, Enum):
    """Explicit data availability state. No fake data is ever substituted."""

    CONNECTED = "CONNECTED"          # fresh data from the provider
    CACHED = "CACHED"                # served from cache, still valid
    STALE = "STALE"                  # last known real data, marked as stale
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"  # provider unreachable -> no values
    MARKET_CLOSED = "MARKET_CLOSED"  # weekend / market closed


class MarketPhase(str, Enum):
    OPEN = "OPEN"
    CLOSED_WEEKEND = "CLOSED_WEEKEND"
    CLOSED_HOLIDAY = "CLOSED_HOLIDAY"
    UNKNOWN = "UNKNOWN"


class TradingSession(str, Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


class Candle(BaseModel):
    """One OHLCV bar. ``time`` is the bar opening time in UTC epoch seconds."""

    time: int = Field(description="Bar open time, UTC epoch seconds")
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    closed: bool = Field(default=True, description="False for the still-forming bar")

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _finite_positive(cls, value: float) -> float:
        if value is None or value != value or value in (float("inf"), float("-inf")):
            raise ValueError("price must be a finite number")
        if value <= 0:
            raise ValueError("price must be > 0")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "Candle":
        # Structural consistency: high >= max(o,c) and low <= min(o,c).
        # Measured against the source with a per-pair tolerance (see quality.py).
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self

    @property
    def opened_at(self) -> datetime:
        return datetime.fromtimestamp(self.time, tz=timezone.utc)

    def mid(self) -> float:
        return (self.high + self.low) / 2


class CandleSeries(BaseModel):
    symbol: str
    timeframe: Timeframe
    provider: str
    candles: list[Candle]
    fetched_at: datetime
    data_state: DataState = DataState.CONNECTED
    stale: bool = False
    quality_warnings: list[str] = Field(default_factory=list)

    @property
    def closed_candles(self) -> list[Candle]:
        return [c for c in self.candles if c.closed]

    @property
    def last_candle(self) -> Candle | None:
        return self.candles[-1] if self.candles else None


class SymbolInfo(BaseModel):
    symbol: str
    description: str
    base: str
    quote: str
    digits: int = 5
    pip_size: float = 0.0001
    asset_class: str = "FOREX"
    provider_symbol: str
    enabled: bool = True


class MarketStatus(BaseModel):
    """Trading-session status derived from the clock, not from prices."""

    phase: MarketPhase = MarketPhase.UNKNOWN
    is_open: bool = False
    active_sessions: list[TradingSession] = Field(default_factory=list)
    reference_time_utc: datetime
    next_open_utc: datetime | None = None
    next_close_utc: datetime | None = None
    note: str | None = None


class QuoteSnapshot(BaseModel):
    """Point-in-time view used by the dashboard header.

    Every price field is ``None`` when the provider could not be reached:
    the frontend then renders DATA UNAVAILABLE instead of a fake value.
    """

    symbol: str
    timeframe: Timeframe
    provider: str
    data_state: DataState
    price: float | None = None
    prev_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    digits: int = 5
    candle_time: datetime | None = None
    last_update: datetime | None = None
    market: MarketStatus | None = None
    stale: bool = False
    error: str | None = None


class ProviderHealth(BaseModel):
    provider: str
    reachable: bool
    last_success_utc: datetime | None = None
    last_error_utc: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    requests_total: int = 0
    requests_failed: int = 0
    average_latency_ms: float | None = None
