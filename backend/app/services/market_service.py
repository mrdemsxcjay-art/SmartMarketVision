"""Market service: provider + cache + persistence + quality checks.

This is the only place the API and the scanner obtain market data from.
It never invents a price: if the provider fails, a typed error is raised and
the caller (API layer) turns it into ``DATA UNAVAILABLE``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.db.repository import CandleRepository, EventRepository
from app.instruments import get_symbol_info, normalize_symbol
from app.logging_conf import get_logger
from app.providers.base import MarketDataProvider
from app.providers.errors import ProviderError, ProviderBadPayload
from app.providers.registry import get_provider
from app.schemas.market import (
    CandleSeries,
    DataState,
    MarketStatus,
    QuoteSnapshot,
    Timeframe,
    as_timeframe,
)
from app.services.cache import SeriesCacheEntry, series_cache
from app.services.quality import analyse_series

logger = get_logger(__name__)

#: after this age (seconds) a cached series is served flagged as STALE
STALE_AFTER_SECONDS = 180


class MarketService:
    def __init__(
        self,
        provider: MarketDataProvider | None = None,
        repository: CandleRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self._provider_override = provider
        self._repository = repository
        self._event_repository = event_repository

    # ------------------------------------------------------------- provider
    @property
    def provider(self) -> MarketDataProvider:
        return self._provider_override or get_provider()

    @property
    def provider_name(self) -> str:
        return self.provider.name

    # -------------------------------------------------------------- candles
    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        limit: int = 400,
        *,
        allow_stale_cache: bool = True,
        persist: bool = True,
    ) -> CandleSeries:
        code = normalize_symbol(symbol)
        tf = as_timeframe(timeframe)
        limit = max(10, min(int(limit), settings.max_candles_per_request))
        key = series_cache.key(code, tf.value, limit)

        cached = series_cache.get(key)
        if cached is not None:
            series = cached.value.model_copy(update={"data_state": DataState.CACHED})
            return series

        try:
            series = await self.provider.get_candles(code, tf, limit)
        except ProviderError as exc:
            stale = series_cache.peek(key) if allow_stale_cache else None
            if stale is not None:
                age = int(stale.age)
                logger.warning(
                    "Provider failed for %s %s (%s) - serving STALE cache (age %ss)",
                    code,
                    tf.value,
                    exc.code,
                    age,
                )
                stale_series = stale.value.model_copy(
                    update={
                        "data_state": DataState.STALE,
                        "stale": True,
                        "quality_warnings": list(
                            dict.fromkeys(
                                stale.value.quality_warnings
                                + [f"provider error {exc.code}: showing last known real data"]
                            )
                        ),
                    }
                )
                return stale_series
            logger.error("Provider failed for %s %s: %s", code, tf.value, exc)
            raise

        info = get_symbol_info(code)
        series = analyse_series(
            series,
            digits=info.digits if info else 5,
            pip_size=info.pip_size if info else 0.0001,
        )
        series_cache.set(key, series, settings.cache_ttl_for(tf.value))

        if persist and self._repository is not None:
            try:
                self._repository.upsert_candles(series, digits=info.digits if info else 5)
            except Exception as exc:  # persistence must never break the API
                logger.error("Failed to persist candles for %s %s: %s", code, tf.value, exc)

        return series

    async def get_quote(self, symbol: str, timeframe: Timeframe | str = "M15") -> QuoteSnapshot:
        """Dashboard header snapshot. On failure all prices stay ``None``."""
        code = normalize_symbol(symbol)
        tf = as_timeframe(timeframe)
        info = get_symbol_info(code)
        now = datetime.now(tz=timezone.utc)

        try:
            series = await self.get_candles(code, tf, limit=120, persist=False)
            price, price_ts = await self._live_price(code, tf.value, series)
            prev_close = None
            closed = series.closed_candles
            if len(closed) >= 2:
                prev_close = closed[-2].close if closed[-1].time == series.candles[-1].time else closed[-1].close
            if price is None:
                price = series.last_candle.close if series.last_candle else None

            change = change_percent = None
            if price is not None and prev_close:
                change = price - prev_close
                change_percent = (change / prev_close) * 100

            age = (now.timestamp() - price_ts) if price_ts else None
            stale = series.stale or bool(age and age > max(series.timeframe.seconds * 3, STALE_AFTER_SECONDS))

            market = await self.get_market_status()
            data_state = series.data_state
            if stale and data_state == DataState.CONNECTED:
                data_state = DataState.STALE

            return QuoteSnapshot(
                symbol=code,
                timeframe=series.timeframe,
                provider=self.provider_name,
                data_state=data_state,
                price=price,
                prev_close=prev_close,
                change=change,
                change_percent=change_percent,
                digits=info.digits if info else 5,
                candle_time=datetime.fromtimestamp(price_ts, tz=timezone.utc) if price_ts else None,
                last_update=series.fetched_at,
                market=market,
                stale=stale,
            )

        except ProviderError as exc:
            logger.error("Quote unavailable for %s %s: %s", code, tf.value, exc)
            return QuoteSnapshot(
                symbol=code,
                timeframe=tf,
                provider=self.provider_name,
                data_state=DataState.DATA_UNAVAILABLE,
                digits=info.digits if info else 5,
                last_update=None,
                stale=True,
                error=f"{exc.code}: {exc.message}",
            )

    async def _live_price(
        self, symbol: str, timeframe: str, series: CandleSeries
    ) -> tuple[float | None, int | None]:
        """Prefer the provider's live quote metadata, else the last bar close."""
        try:
            price, ts = await self.provider.get_quote(symbol, timeframe)
        except ProviderError as exc:
            logger.debug("Live quote metadata unavailable for %s (%s)", symbol, exc.code)
            price, ts = None, None
        if price is None:
            last = series.last_candle
            return (last.close if last else None), (last.time if last else None)
        return price, ts

    async def get_market_status(self) -> MarketStatus:
        try:
            return await self.provider.get_market_status()
        except ProviderError as exc:
            logger.error("Market status unavailable: %s", exc)
            return MarketStatus(
                phase="UNKNOWN",  # type: ignore[arg-type]
                is_open=False,
                reference_time_utc=datetime.now(tz=timezone.utc),
                note=f"status unavailable: {exc.code}",
            )

    async def get_symbols(self) -> list[dict]:
        try:
            infos = await self.provider.get_symbols()
        except ProviderError as exc:
            logger.error("Symbol list unavailable: %s", exc)
            infos = []
        enriched: list[dict] = []
        for info in infos:
            cached = series_cache.peek(series_cache.key(info.symbol, "M15", 400))
            enriched.append(
                {
                    **info.model_dump(),
                    "provider": self.provider_name,
                    "cached_at": cached.value.fetched_at.isoformat() if cached else None,
                }
            )
        return enriched

    async def warm(self, symbols: list[str], timeframe: str, limit: int) -> None:
        """Best-effort cache warm-up used at startup. Errors are logged only."""
        for symbol in symbols:
            try:
                await self.get_candles(symbol, timeframe, limit=limit)
            except ProviderError as exc:
                logger.warning("Warm-up failed for %s %s: %s", symbol, timeframe, exc.code)


async def ensure_series_available(series: CandleSeries | None) -> bool:
    """Small helper used by the API layer for explicit DATA UNAVAILABLE logic."""
    if series is None or not series.candles:
        raise ProviderBadPayload("no data available")


#: re-exported for convenience
CacheEntry = SeriesCacheEntry
