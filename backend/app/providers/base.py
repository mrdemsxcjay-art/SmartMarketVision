"""MarketDataProvider contract.

Any concrete provider (Yahoo Finance today, a broker feed or a paid vendor
later) must implement this interface. The rest of the application only
depends on the abstract type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas.market import Candle, CandleSeries, MarketStatus, ProviderHealth, SymbolInfo, Timeframe


class MarketDataProvider(ABC):
    """Read-only market data source.

    Implementations MUST NOT contain any order-execution capability, and MUST
    raise a :class:`~app.providers.errors.ProviderError` subclass instead of
    returning invented values.
    """

    #: stable identifier used in API payloads and stored with every candle
    name: str = "abstract"
    #: human readable description
    description: str = ""

    @abstractmethod
    async def get_symbols(self) -> list[SymbolInfo]:
        """Return the instruments available on this provider."""

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        limit: int = 400,
    ) -> CandleSeries:
        """Return up to ``limit`` most recent OHLCV bars, oldest first.

        The final element may be the bar still forming (``closed=False``).
        Implementations must never return bars whose open time is in the future.
        """

    @abstractmethod
    async def get_latest_candle(self, symbol: str, timeframe: Timeframe | str) -> Candle:
        """Return the most recent bar (may be forming)."""

    @abstractmethod
    async def get_market_status(self, now: "datetime | None" = None) -> MarketStatus:
        """Return the trading-session state of the market.

        ``now`` (UTC) is injectable so the weekly schedule can be tested
        deterministically; production calls leave it to None.
        """

    async def get_quote(self, symbol: str, timeframe: Timeframe | str) -> tuple[float | None, int | None]:
        """Optional: latest tradable price and its epoch time.

        Default implementation derives it from :meth:`get_latest_candle`.
        """
        candle = await self.get_latest_candle(symbol, timeframe)
        return candle.close, candle.time

    async def health(self) -> ProviderHealth:
        """Optional provider health snapshot."""
        return ProviderHealth(provider=self.name, reachable=True)

    async def aclose(self) -> None:
        """Release network resources. Safe to call multiple times."""
        return None
