"""Provider tests: parsing, alignment, error handling and market clock.

The Yahoo provider is exercised offline through an httpx MockTransport that
replays payloads shaped exactly like the real upstream responses.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.instruments import get_symbol_info
from app.providers.errors import (
    ProviderBadPayload,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    UnknownSymbol,
    UnsupportedTimeframe,
)
from app.providers.yahoo import HOSTS, YahooForexProvider
from app.schemas.market import MarketPhase, Timeframe

from tests.conftest import utc


def build_payload(timestamps, opens, highs, lows, closes, volumes=None):
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "EURUSD=X",
                        "regularMarketPrice": closes[-1] if closes else None,
                        "regularMarketTime": timestamps[-1] if timestamps else None,
                    },
                    "timestamp": list(timestamps),
                    "indicators": {
                        "quote": [
                            {
                                "open": list(opens),
                                "high": list(highs),
                                "low": list(lows),
                                "close": list(closes),
                                "volume": list(volumes) if volumes else [None] * len(closes),
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def make_provider(handler, **kwargs) -> YahooForexProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return YahooForexProvider(client=client, **kwargs)


@pytest.mark.asyncio
async def test_parses_real_shaped_payload():
    base = 1790000000 // 900 * 900
    timestamps = [base + i * 900 for i in range(5)]
    opens = [1.1000, 1.1005, 1.1010, 1.1008, 1.1012]
    highs = [o + 0.0008 for o in opens]
    lows = [o - 0.0008 for o in opens]
    closes = [1.1005, 1.1010, 1.1008, 1.1012, 1.1015]
    provider = make_provider(lambda request: httpx.Response(200, json=build_payload(timestamps, opens, highs, lows, closes)))

    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 5
    assert series.symbol == "EURUSD"
    assert series.timeframe is Timeframe.M15
    assert series.provider == "yahoo"
    assert [c.time for c in series.candles] == timestamps
    for candle in series.candles:
        assert candle.high >= max(candle.open, candle.close)
        assert candle.low <= min(candle.open, candle.close)


@pytest.mark.asyncio
async def test_drops_incomplete_and_future_bars():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    base = now // 900 * 900 - 900 * 3
    # the future bar is deliberately 2 h ahead: the provider tolerates 60 s of
    # clock skew, so a bar landing right after the current boundary would be
    # legitimately kept as the forming bar and make this test clock-dependent
    timestamps = [base, base + 900, base + 1800, base + 7200]
    opens = [1.10, 1.11, None, 1.12]
    highs = [1.101, 1.111, None, 1.121]
    lows = [1.099, 1.109, None, 1.119]
    closes = [1.1005, 1.1105, None, 1.1205]
    provider = make_provider(lambda request: httpx.Response(200, json=build_payload(timestamps, opens, highs, lows, closes)))

    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 2
    assert all(c.time <= now for c in series.candles)
    assert any("future" in w for w in series.quality_warnings)


@pytest.mark.asyncio
async def test_running_daily_bar_is_restamped_on_its_period_start():
    """Upstream stamps the in-progress D1 bar with "now" (e.g. 00:19:43) instead
    of the exchange midnight. The OHLC are real, only the stamp must be aligned."""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    # the exchange midnight used by the feed is 23:00 UTC
    midnight = ((now - 82800) // 86400) * 86400 + 82800
    timestamps = [midnight - 86400, midnight - 2 * 86400, now - 120]
    opens = [157.10, 157.00, 157.24]
    highs = [157.60, 157.20, 157.46]
    lows = [156.90, 156.80, 157.22]
    closes = [157.30, 157.05, 157.31]
    provider = make_provider(lambda request: httpx.Response(200, json=build_payload(timestamps, opens, highs, lows, closes)))

    series = await provider.get_candles("USDJPY", "D1", limit=10)
    running = series.candles[-1]
    assert running.time % 86400 == midnight % 86400, "the running bar must sit on the daily grid"
    assert running.close == 157.31, "the real price is kept unchanged"
    assert running.closed is False, "the running period is never reported as closed"
    assert any("running bar" in warning for warning in series.quality_warnings)


@pytest.mark.asyncio
async def test_a_closed_off_grid_daily_bar_is_not_moved():
    """Only the *running* bar may be re-stamped: a closed bar keeps its stamp."""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    old = now - 10 * 86400
    # both bars are long closed and deliberately off-grid (2 h past the anchor);
    # only the last one could be mistaken for a running bar, and it is not one
    timestamps = [old, old + 86400 + 7200]
    opens = highs = lows = closes = [1.10, 1.11]
    provider = make_provider(lambda request: httpx.Response(200, json=build_payload(timestamps, opens, highs, lows, closes)))

    series = await provider.get_candles("EURUSD", "D1", limit=10)
    assert [candle.time for candle in series.candles] == [old, old + 86400 + 7200]


@pytest.mark.asyncio
async def test_partial_bar_is_folded_into_running_period():
    """Upstream sends an aligned bar plus a partial bar stamped with 'now'."""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    # the whole fixture is pushed 5+ minutes into the past so that neither the
    # aligned bar nor the partial one can be mistaken for a future bar when the
    # test happens to run right after a 15-minute boundary (clock independence)
    aligned = (now - 300) // 900 * 900
    timestamps = [aligned - 900, aligned, aligned + 240]  # partial bar inside the period
    opens = [1.1000, 1.1010, 1.1010]
    highs = [1.1005, 1.1015, 1.1030]
    lows = [1.0995, 1.1005, 1.1000]
    closes = [1.1010, 1.1012, 1.1025]
    provider = make_provider(lambda request: httpx.Response(200, json=build_payload(timestamps, opens, highs, lows, closes)))

    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 2, "the partial bar must not create a phantom bar"
    running = series.candles[-1]
    assert running.time == aligned
    assert running.open == 1.1010  # first open kept
    assert running.close == 1.1025  # newest close kept
    assert running.high == 1.1030  # high extended
    assert running.low == 1.1000
    assert any("partial" in w for w in series.quality_warnings)


@pytest.mark.asyncio
async def test_one_second_offset_is_snapped_to_grid():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    aligned = now // 300 * 300
    timestamps = [aligned - 600, aligned - 300, aligned + 1]  # 1s late bar
    provider = make_provider(
        lambda request: httpx.Response(
            200,
            json=build_payload(timestamps, [1.1] * 3, [1.11] * 3, [1.09] * 3, [1.105] * 3),
        )
    )
    series = await provider.get_candles("EURUSD", "M5", limit=10)
    assert series.candles[-1].time == aligned
    assert all(c.time % 300 == 0 for c in series.candles)
    assert any("snapped" in w for w in series.quality_warnings)


@pytest.mark.asyncio
async def test_duplicate_timestamps_are_merged_not_duplicated():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    aligned = now // 900 * 900 - 900
    timestamps = [aligned, aligned + 1, aligned + 2]
    provider = make_provider(
        lambda request: httpx.Response(
            200,
            json=build_payload(timestamps, [1.10] * 3, [1.10, 1.12, 1.11], [1.09, 1.08, 1.085], [1.10, 1.11, 1.105]),
        )
    )
    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 1
    candle = series.candles[0]
    assert candle.high == 1.12 and candle.low == 1.08 and candle.close == 1.105


@pytest.mark.asyncio
async def test_limit_and_ordering():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    base = now // 900 * 900 - 900 * 50
    timestamps = [base + i * 900 for i in range(50)]
    provider = make_provider(
        lambda request: httpx.Response(
            200, json=build_payload(timestamps, [1.1] * 50, [1.11] * 50, [1.09] * 50, [1.105] * 50)
        )
    )
    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 10
    times = [c.time for c in series.candles]
    assert times == sorted(times)
    assert times[-1] == timestamps[-1]


@pytest.mark.asyncio
async def test_empty_result_raises_bad_payload():
    provider = make_provider(lambda request: httpx.Response(200, json={"chart": {"result": None, "error": None}}))
    with pytest.raises(ProviderBadPayload):
        await provider.get_candles("EURUSD", "M15", limit=10)


@pytest.mark.asyncio
async def test_upstream_error_message_is_surfaced():
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"}}}
    provider = make_provider(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ProviderBadPayload) as exc:
        await provider.get_candles("EURUSD", "M15", limit=10)
    assert "delisted" in str(exc.value).lower() or "no data found" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_rate_limit_is_retried_then_raises_rate_limited():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="Too Many Requests")

    provider = make_provider(handler)
    with pytest.raises(ProviderRateLimited):
        await provider.get_candles("EURUSD", "M15", limit=10)
    assert calls["n"] >= 2, "a retryable error must be retried on another host"


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="Service Unavailable")
        now = int(datetime.now(tz=timezone.utc).timestamp())
        aligned = now // 900 * 900 - 900
        return httpx.Response(
            200,
            json=build_payload([aligned, aligned + 900], [1.1, 1.1], [1.11, 1.11], [1.09, 1.09], [1.10, 1.105]),
        )

    provider = make_provider(handler)
    series = await provider.get_candles("EURUSD", "M15", limit=10)
    assert len(series.candles) == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_timeout_is_translated():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderTimeout):
        await provider.get_candles("EURUSD", "M15", limit=10)


@pytest.mark.asyncio
async def test_server_error_is_translated():
    provider = make_provider(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(ProviderUnavailable):
        await provider.get_candles("EURUSD", "M15", limit=10)


@pytest.mark.asyncio
async def test_unknown_symbol_and_timeframe():
    provider = make_provider(lambda request: httpx.Response(200, json={"chart": {"result": [], "error": None}}))
    with pytest.raises(UnknownSymbol):
        await provider.get_candles("ZZZQQQ", "M15", limit=10)
    with pytest.raises(UnsupportedTimeframe):
        await provider.get_candles("EURUSD", "W1", limit=10)


@pytest.mark.asyncio
async def test_health_tracking_after_failure_and_success():
    state = {"fail": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(503, text="down")
        now = int(datetime.now(tz=timezone.utc).timestamp())
        aligned = now // 900 * 900 - 900
        return httpx.Response(
            200, json=build_payload([aligned], [1.1], [1.11], [1.09], [1.10])
        )

    provider = make_provider(handler)
    with pytest.raises(ProviderUnavailable):
        await provider.get_candles("EURUSD", "M15", limit=10)
    health = await provider.health()
    assert health.reachable is False
    assert health.consecutive_failures >= 1
    assert health.last_error

    state["fail"] = False
    await provider.get_candles("EURUSD", "M15", limit=10)
    health = await provider.health()
    assert health.reachable is True
    assert health.consecutive_failures == 0
    assert health.average_latency_ms is not None


@pytest.mark.asyncio
async def test_get_quote_uses_market_metadata():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    aligned = now // 900 * 900 - 900
    provider = make_provider(
        lambda request: httpx.Response(
            200, json=build_payload([aligned], [1.1], [1.11], [1.09], [1.105])
        )
    )
    price, ts = await provider.get_quote("EURUSD", "M15")
    assert price == pytest.approx(1.105)
    assert ts == aligned


# --------------------------------------------------------------- market clock
class TestMarketClock:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "moment,expected_phase,expected_open",
        [
            (utc(2026, 9, 29, 12, 0), MarketPhase.OPEN, True),          # Tuesday
            (utc(2026, 10, 2, 20, 59), MarketPhase.OPEN, True),          # Friday before 17:00 ET
            (utc(2026, 10, 2, 21, 30), MarketPhase.CLOSED_WEEKEND, False),  # Friday after close
            (utc(2026, 10, 3, 12, 0), MarketPhase.CLOSED_WEEKEND, False),   # Saturday
            (utc(2026, 10, 4, 12, 0), MarketPhase.CLOSED_WEEKEND, False),   # Sunday before open
            (utc(2026, 10, 4, 21, 30), MarketPhase.OPEN, True),          # Sunday after 17:00 ET
        ],
    )
    async def test_weekly_schedule(self, moment, expected_phase, expected_open):
        provider = make_provider(lambda request: httpx.Response(200, json={}))
        status = await provider.get_market_status(now=moment)
        assert status.phase is expected_phase
        assert status.is_open is expected_open
        assert status.reference_time_utc == moment
        if not status.is_open:
            assert status.next_open_utc is not None
            assert status.next_open_utc > moment

    @pytest.mark.asyncio
    async def test_sessions_are_reported_during_the_week(self):
        provider = make_provider(lambda request: httpx.Response(200, json={}))
        status = await provider.get_market_status(now=utc(2026, 9, 29, 9, 0))  # London morning
        assert "LONDON" in status.active_sessions


def test_provider_market_status_matches_interface():
    """The abstract interface must stay the single source of truth."""
    import inspect

    from app.providers.base import MarketDataProvider

    for method in ("get_symbols", "get_candles", "get_latest_candle", "get_market_status"):
        assert hasattr(MarketDataProvider, method), method
    signature = inspect.signature(MarketDataProvider.get_market_status)
    assert "now" in signature.parameters


def test_instrument_metadata_digits():
    assert get_symbol_info("EURUSD").digits == 5
    assert get_symbol_info("USDJPY").digits == 3
    assert get_symbol_info("eur/usd").symbol == "EURUSD"
    assert get_symbol_info("UNKNOWN") is None


def test_hosts_rotation_has_two_endpoints():
    assert len(HOSTS) == 2
