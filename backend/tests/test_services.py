"""Service-layer tests: quality checks, cache TTL, stale fallback, persistence."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.db.repository import CandleRepository, EventRepository, ScannerRunRepository
from app.providers.errors import ProviderUnavailable
from app.schemas.market import Candle, CandleSeries, DataState, Timeframe
from app.services.cache import SeriesCache
from app.services.market_service import MarketService
from app.services.quality import (
    check_completeness,
    check_ohlc_consistency,
    check_timestamps,
    analyse_series,
)

from tests.conftest import FakeProvider, make_candles


def series_from(candles: list[Candle], tf: Timeframe = Timeframe.M15) -> CandleSeries:
    return CandleSeries(
        symbol="EURUSD",
        timeframe=tf,
        provider="test",
        candles=candles,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class TestQuality:
    def test_detects_future_bars(self):
        now = int(time.time())
        candles = make_candles([1.1, 1.1, 1.1], timeframe=Timeframe.M15, end_time=now + 3600)
        warnings = check_timestamps(series_from(candles))
        assert any("future" in w for w in warnings)

    def test_detects_duplicate_and_unsorted_timestamps(self):
        now = int(time.time()) // 900 * 900
        candles = [
            Candle(time=now, open=1.1, high=1.11, low=1.09, close=1.1),
            Candle(time=now, open=1.1, high=1.11, low=1.09, close=1.1),
            Candle(time=now - 900, open=1.1, high=1.11, low=1.09, close=1.1),
        ]
        warnings = check_timestamps(series_from(candles))
        assert any("duplicate" in w for w in warnings)
        assert any("increasing" in w for w in warnings)

    def test_flags_stale_series(self):
        old = int(time.time()) - 5 * 3600
        candles = make_candles([1.1, 1.2, 1.15], timeframe=Timeframe.M15, end_time=old)
        warnings = check_timestamps(series_from(candles))
        assert any("old" in w for w in warnings)

    def test_ohlc_tolerance_is_in_pips(self):
        now = int(time.time()) // 900 * 900
        # 0.1 pip deviation -> inside tolerance (source rounding)
        inside = Candle(time=now, open=1.10000, high=1.10009, low=1.09995, close=1.10010)
        # 1.5 pip deviation -> real inconsistency
        outside = Candle(time=now + 900, open=1.09990, high=1.09995, low=1.09900, close=1.10010)
        warnings = check_ohlc_consistency(series_from([inside, outside]), digits=5, pip_size=0.0001)
        assert len(warnings) == 1
        assert "rounding" in warnings[0]

    def test_weekend_gap_is_not_flagged_but_long_hole_is(self):
        now = int(time.time()) // 3600 * 3600
        weekend = [  # 48h apart: the normal Forex weekend break
            Candle(time=now - 48 * 3600, open=1.1, high=1.11, low=1.09, close=1.1),
            Candle(time=now, open=1.1, high=1.11, low=1.09, close=1.1),
        ]
        assert check_completeness(series_from(weekend, Timeframe.H1)) == []

        hole = [  # 10 days apart: a real hole in the feed
            Candle(time=now - 240 * 3600, open=1.1, high=1.11, low=1.09, close=1.1),
            Candle(time=now, open=1.1, high=1.11, low=1.09, close=1.1),
        ]
        warnings = check_completeness(series_from(hole, Timeframe.H1))
        assert warnings and "longer than 3.5 days" in warnings[0]

    def test_daily_series_ignores_weekend_gaps(self):
        now = int(time.time()) // 86400 * 86400
        daily = [
            Candle(time=now - 3 * 86400, open=1.1, high=1.11, low=1.09, close=1.1),
            Candle(time=now, open=1.1, high=1.11, low=1.09, close=1.1),
        ]
        assert check_completeness(series_from(daily, Timeframe.D1)) == []

    def test_series_analysis_does_not_modify_prices(self):
        candles = make_candles([1.1, 1.2, 1.15])
        before = [(c.open, c.high, c.low, c.close) for c in candles]
        series = analyse_series(series_from(candles))
        after = [(c.open, c.high, c.low, c.close) for c in series.candles]
        assert before == after


class TestCache:
    def test_ttl_expiry(self):
        cache = SeriesCache()
        series = series_from(make_candles([1.1, 1.2]))
        cache.set("EURUSD:M15:10", series, ttl=0.05)
        assert cache.get("EURUSD:M15:10") is not None
        time.sleep(0.06)
        assert cache.get("EURUSD:M15:10") is None
        assert cache.peek("EURUSD:M15:10") is not None, "expired entry is still available for stale fallback"

    def test_key_uses_normalised_timeframe(self):
        assert SeriesCache.key("eurusd", Timeframe.M15, 10) == "EURUSD:M15:10"
        assert SeriesCache.key("EURUSD", "m15", 10) == "EURUSD:M15:10"

    def test_invalidate(self):
        cache = SeriesCache()
        cache.set("A", series_from(make_candles([1.0, 1.1])), ttl=60)
        cache.invalidate()
        assert cache.stats()["entries"] == 0


class TestMarketService:
    @pytest.mark.asyncio
    async def test_uses_cache_inside_ttl(self):
        provider = FakeProvider()
        service = MarketService(provider=provider)
        await service.get_candles("EURUSD", "M15", limit=50)
        calls_after_first = provider.calls
        second = await service.get_candles("EURUSD", "M15", limit=50)
        assert provider.calls == calls_after_first, "the provider must not be called again inside the TTL"
        assert second.data_state is DataState.CACHED

    @pytest.mark.asyncio
    async def test_falls_back_to_stale_cache_when_provider_fails(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "cache_ttl_m15", 0)  # expire the entry immediately
        provider = FakeProvider()
        service = MarketService(provider=provider)
        await service.get_candles("EURUSD", "M15", limit=50)
        provider.fail_with = ProviderUnavailable("down (test)")
        series = await service.get_candles("EURUSD", "M15", limit=50)
        assert series.data_state is DataState.STALE
        assert series.stale is True
        assert series.candles, "the last real candles must still be served"
        assert any("provider error" in w for w in series.quality_warnings)

    @pytest.mark.asyncio
    async def test_raises_when_never_cached(self):
        provider = FakeProvider()
        provider.fail_with = ProviderUnavailable("down (test)")
        service = MarketService(provider=provider)
        with pytest.raises(ProviderUnavailable):
            await service.get_candles("EURUSD", "M15", limit=50)

    @pytest.mark.asyncio
    async def test_quote_returns_data_unavailable_without_price(self):
        provider = FakeProvider()
        provider.fail_with = ProviderUnavailable("down (test)")
        service = MarketService(provider=provider)
        quote = await service.get_quote("EURUSD", "M15")
        assert quote.data_state is DataState.DATA_UNAVAILABLE
        assert quote.price is None
        assert quote.change is None
        assert quote.error and "PROVIDER_UNAVAILABLE" in quote.error

    @pytest.mark.asyncio
    async def test_quote_computes_change_from_real_closes(self):
        candles = make_candles([1.1000, 1.1020, 1.1040], closed=True)
        provider = FakeProvider(candles=candles)
        service = MarketService(provider=provider)
        quote = await service.get_quote("EURUSD", "M15")
        assert quote.price is not None
        assert quote.prev_close is not None
        assert quote.change == pytest.approx(quote.price - quote.prev_close)

    @pytest.mark.asyncio
    async def test_candles_are_persisted(self):
        repo = CandleRepository()
        provider = FakeProvider()
        service = MarketService(provider=provider, repository=repo)
        await service.get_candles("EURUSD", "M15", limit=30)
        assert repo.count("EURUSD", "M15") >= 30  # the DB is shared across the session
        stored = repo.get_candles("EURUSD", "M15", limit=5)
        assert len(stored) == 5
        assert stored == sorted(stored, key=lambda c: c.time)

    @pytest.mark.asyncio
    async def test_symbols_are_enriched(self):
        service = MarketService(provider=FakeProvider())
        symbols = await service.get_symbols()
        assert {s["symbol"] for s in symbols} == {"EURUSD", "USDJPY"}
        assert all("provider" in s for s in symbols)


class TestRepositories:
    @pytest.mark.asyncio
    async def test_event_and_run_repositories(self):
        from app.schemas.events import EventType, MarketEvent

        events = EventRepository()
        runs = ScannerRunRepository()

        events.save(
            MarketEvent(event_type=EventType.MARKET_UPDATE, symbol="EURUSD", timeframe=Timeframe.M15, price=1.1)
        )
        assert events.count() >= 1
        recent = events.recent(limit=5)
        assert recent[0]["symbol"] == "EURUSD"

        run_id = runs.start("test-provider")
        runs.finish(run_id, pairs_scanned=10, pairs_failed=1, errors=["EURUSD M15: test"])
        last = runs.last()
        assert last["pairs_scanned"] == 10
        assert last["pairs_failed"] == 1
        assert last["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent_on_the_same_bar(self):
        repo = CandleRepository()
        provider = FakeProvider()
        service = MarketService(provider=provider)
        series = await service.get_candles("EURUSD", "M15", limit=20, persist=False)
        repo.upsert_candles(series)
        first = repo.count("EURUSD", "M15")
        repo.upsert_candles(series)
        assert repo.count("EURUSD", "M15") == first

    def test_purge_older_than(self):
        repo = CandleRepository()
        old = int((datetime.now(tz=timezone.utc) - timedelta(days=400)).timestamp())
        repo.upsert_candles(series_from([Candle(time=old, open=1.1, high=1.2, low=1.0, close=1.15)]))
        before = repo.count()
        removed = repo.purge_older_than(120)
        assert removed >= 1
        assert repo.count() <= before
