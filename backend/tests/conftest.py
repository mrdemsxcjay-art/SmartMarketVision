"""Pytest fixtures.

Test data lives ONLY here and in the test modules: the application code never
generates synthetic prices, and every test that needs candles builds them
explicitly through :func:`make_candles`.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Configuration must be set before the app package reads it.
_TMP_DB_DIR = Path(tempfile.mkdtemp(prefix="smv-tests-"))
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TMP_DB_DIR / 'test.db'}"
os.environ["SCANNER_ENABLED"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["MARKET_DATA_PROVIDER"] = "yahoo"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("TELEGRAM_CHAT_ID", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.container import Container  # noqa: E402
from app.db.base import init_db  # noqa: E402
from app.instruments import get_symbol_info  # noqa: E402
from app.providers.base import MarketDataProvider  # noqa: E402
from app.providers.errors import ProviderRateLimited, ProviderUnavailable, UnknownSymbol  # noqa: E402
from app.schemas.market import (  # noqa: E402
    Candle,
    CandleSeries,
    DataState,
    MarketPhase,
    MarketStatus,
    SymbolInfo,
    Timeframe,
)
from app.services.cache import series_cache  # noqa: E402

TF_SECONDS = {tf: tf.seconds for tf in Timeframe}


def make_candles(
    closes: list[float],
    *,
    timeframe: Timeframe = Timeframe.M15,
    end_time: int | None = None,
    spread: float = 0.0010,
    closed: bool = True,
) -> list[Candle]:
    """Build a deterministic candle list from closes (test fixture only)."""
    step = timeframe.seconds
    last_open = end_time if end_time is not None else int(time.time()) // step * step
    start = last_open - step * (len(closes) - 1)
    candles: list[Candle] = []
    for i, close in enumerate(closes):
        # Opens sit halfway back to the previous close, which keeps wicks
        # strictly separated so pivot detection is unambiguous.
        open_ = (closes[i - 1] + close) / 2 if i else close
        high = max(open_, close) + spread
        low = min(open_, close) - spread
        candles.append(
            Candle(
                time=start + i * step,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=100.0 + i,
                closed=closed,
            )
        )
    return candles


def candles_from_ranges(
    ranges: list[tuple[float, float]],
    *,
    timeframe: Timeframe = Timeframe.H1,
    end_time: int | None = None,
    closed: bool = True,
    closed_last: bool | None = None,
) -> list[Candle]:
    """Build candles from explicit ``(high, low)`` ranges (test fixture only).

    ``open`` and ``close`` sit at the middle of the range, which makes pivots
    unambiguous: a bar is a swing high only if its range is strictly higher than
    its neighbours.
    """
    step = timeframe.seconds
    last_open = end_time if end_time is not None else int(time.time()) // step * step
    start = last_open - step * (len(ranges) - 1)
    candles: list[Candle] = []
    for i, (high, low) in enumerate(ranges):
        mid = round((high + low) / 2, 6)
        is_last = i == len(ranges) - 1
        candles.append(
            Candle(
                time=start + i * step,
                open=mid,
                high=high,
                low=low,
                close=mid,
                volume=100.0 + i,
                closed=closed_last if (is_last and closed_last is not None) else closed,
            )
        )
    return candles


class FakeProvider(MarketDataProvider):
    """Offline provider: returns the candles explicitly handed to it.

    ``fail_with`` switches it to failure mode so DATA UNAVAILABLE paths and
    stale-cache fallbacks can be tested without touching the network.
    """

    name = "fake"
    description = "Deterministic offline provider used by the test suite"

    def __init__(self, candles: list[Candle] | None = None, timeframe: Timeframe = Timeframe.M15) -> None:
        self.candles = candles if candles is not None else make_candles(
            [1.0800 + i * 0.0005 for i in range(120)], timeframe=timeframe
        )
        self.fail_with: Exception | None = None
        self.calls = 0
        self.last_limit: int | None = None

    def _series(self, symbol: str, timeframe: Timeframe, limit: int) -> CandleSeries:
        return CandleSeries(
            symbol=symbol.upper(),
            timeframe=timeframe,
            provider=self.name,
            candles=self.candles[-limit:],
            fetched_at=datetime.now(tz=timezone.utc),
            data_state=DataState.CONNECTED,
        )

    async def get_symbols(self) -> list[SymbolInfo]:
        return [info for code in ("EURUSD", "USDJPY") if (info := get_symbol_info(code))]

    async def get_candles(self, symbol: str, timeframe: Timeframe | str, limit: int = 400) -> CandleSeries:
        self.calls += 1
        self.last_limit = limit
        if self.fail_with:
            raise self.fail_with
        if get_symbol_info(str(symbol)) is None:
            raise UnknownSymbol(f"unknown symbol {symbol}")
        return self._series(str(symbol), Timeframe(str(timeframe).upper()) if not isinstance(timeframe, Timeframe) else timeframe, limit)

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe | str) -> Candle:
        series = await self.get_candles(symbol, timeframe, limit=2)
        return series.candles[-1]

    async def get_quote(self, symbol: str, timeframe: Timeframe | str) -> tuple[float | None, int | None]:
        series = await self.get_candles(symbol, timeframe, limit=2)
        return series.candles[-1].close, series.candles[-1].time

    async def get_market_status(self, now: datetime | None = None) -> MarketStatus:
        return MarketStatus(
            phase=MarketPhase.OPEN,
            is_open=True,
            active_sessions=[],
            reference_time_utc=now or datetime.now(tz=timezone.utc),
        )


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create the schema once for the whole test session."""
    init_db()
    yield


@pytest.fixture(autouse=True)
def clean_state(_database):
    """Isolate every test: fresh cache and empty Phase 2 tables.

    Detections are persisted on purpose, so they would leak from one test to the
    next if the rows were not cleared here.
    """
    series_cache.invalidate()
    _truncate_market_tables()
    yield
    series_cache.invalidate()


def _truncate_market_tables() -> None:
    from sqlalchemy import text

    from app.db.base import engine

    with engine.begin() as connection:
        for table in ("pattern_detections", "market_events", "scanner_runs", "candles"):
            try:
                connection.execute(text(f"DELETE FROM {table}"))
            except Exception:  # table not created yet on the very first test
                pass


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def container(provider: FakeProvider) -> Container:
    from app.db.repository import CandleRepository, DetectionRepository, EventRepository, ScannerRunRepository
    from app.patterns.engine import ChartPatternEngine
    from app.patterns.params import PatternParams
    from app.price_action.engine import PriceActionEngine
    from app.price_action.params import PriceActionParams
    from app.services.events import EventBus
    from app.services.market_service import MarketService
    from app.services.patterns import PatternService
    from app.services.price_action import PriceActionService
    from app.services.scanner import MarketScanner
    from app.services.telegram import TelegramNotifier
    from app.services.visual_capture import ChartSnapshotService

    init_db()
    bus = EventBus()
    candles_repo = CandleRepository()
    events_repo = EventRepository()
    runs_repo = ScannerRunRepository()
    detections_repo = DetectionRepository()
    market = MarketService(provider=provider, repository=candles_repo, event_repository=events_repo)
    # a fresh parameter set per test: an API override can never leak into another test
    patterns = PatternService(
        engine=ChartPatternEngine(PatternParams()),
        bus=bus,
        detection_repository=detections_repo,
        event_repository=events_repo,
    )
    # Phase 3: a fresh price-action engine (its own parameter set) per test, so an
    # API override on one engine can never leak into the other
    from app.services.smc_ict import SmcIctService
    from app.smc_ict.engine import SmcIctEngine
    from app.smc_ict.params import SmcIctParams

    price_action = PriceActionService(
        engine=PriceActionEngine(PriceActionParams()),
        bus=bus,
        detection_repository=detections_repo,
        event_repository=events_repo,
    )
    # Phase 4: a fresh SMC/ICT engine (its own parameter set) per test
    smc_ict = SmcIctService(
        engine=SmcIctEngine(SmcIctParams()),
        bus=bus,
        detection_repository=detections_repo,
        event_repository=events_repo,
    )
    scanner = MarketScanner(
        market_service=market,
        bus=bus,
        event_repository=events_repo,
        run_repository=runs_repo,
        pattern_service=patterns,
        price_action_service=price_action,
        smc_ict_service=smc_ict,
    )
    return Container(
        market=market,
        scanner=scanner,
        bus=bus,
        notifier=TelegramNotifier(bot_token=None, chat_id=None),
        snapshots=ChartSnapshotService(),
        candles_repo=candles_repo,
        events_repo=events_repo,
        detections_repo=detections_repo,
        runs_repo=runs_repo,
        patterns=patterns,
        price_action=price_action,
        smc_ict=smc_ict,
    )


@pytest.fixture
def ctx_candles():
    """Explicit OHLC used by the pivot tests (tests only - never production data)."""
    from tests.pattern_fixtures import double_top

    return list(double_top().series.candles)


@pytest.fixture
def engine():
    """A fresh chartist engine with its own parameter set (isolated per test)."""
    from app.patterns.engine import ChartPatternEngine
    from app.patterns.params import PatternParams

    return ChartPatternEngine(PatternParams())


@pytest.fixture
def client(container: Container):
    from app.main import app

    app.state.container = container
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def failing_provider(provider: FakeProvider) -> FakeProvider:
    provider.fail_with = ProviderUnavailable("upstream down (test)")
    return provider


@pytest.fixture
def rate_limited_provider(provider: FakeProvider) -> FakeProvider:
    provider.fail_with = ProviderRateLimited("429 from upstream (test)")
    return provider


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


__all__ = ["make_candles", "FakeProvider", "utc", "timedelta"]
