"""Yahoo Finance chart provider - real Forex data, no API key required.

Endpoint used (read-only, public):
    GET https://query{1,2}.finance.yahoo.com/v8/finance/chart/{SYMBOL}=X
        ?interval={5m|15m|1h|4h|1d}&range={...}

Guarantees enforced here:
* only real OHLCV returned by the upstream API is used - nothing is invented;
* bars whose open time is in the future are dropped;
* bars with null prices are dropped (weekend / holiday gaps);
* every failure raises a typed ProviderError carrying the root cause.

This provider has no order, account or position capability whatsoever.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.instruments import get_symbol_info, normalize_symbol
from app.logging_conf import get_logger
from app.providers.base import MarketDataProvider
from app.providers.errors import (
    ProviderBadPayload,
    ProviderError,
    ProviderDisabled,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    UnknownSymbol,
    UnsupportedTimeframe,
)
from app.schemas.market import (
    Candle,
    CandleSeries,
    DataState,
    MarketPhase,
    MarketStatus,
    ProviderHealth,
    SymbolInfo,
    Timeframe,
    TradingSession,
    as_timeframe,
)

logger = get_logger(__name__)

HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")

#: The upstream edge returns HTTP 429 for some User-Agent fingerprints
#: (measured 2026-09-29: a full desktop-Chrome UA and tool UAs are rejected,
#: the values below are accepted). Both host and UA rotate on retry.
USER_AGENTS = (
    "SmartMarketVision/1.0 (read-only market scanner)",
    "Mozilla/5.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
)

INTERVAL_MAP: dict[Timeframe, str] = {
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}

# Per timeframe: ascending (range, approximate_capacity) candidates.
# Capacities measured against the live endpoint on 2026-09-29.
RANGE_LADDER: dict[Timeframe, list[tuple[str, int]]] = {
    Timeframe.M5: [("5d", 1150), ("1mo", 6300)],
    Timeframe.M15: [("5d", 385), ("1mo", 2100)],
    Timeframe.H1: [("1mo", 480), ("3mo", 1580)],
    Timeframe.H4: [("3mo", 390), ("1y", 1560)],
    Timeframe.D1: [("1y", 260), ("2y", 520), ("5y", 1300)],
}

NY = ZoneInfo("America/New_York")
SESSION_ZONES = {
    TradingSession.SYDNEY: (ZoneInfo("Australia/Sydney"), 8, 17),
    TradingSession.TOKYO: (ZoneInfo("Asia/Tokyo"), 9, 18),
    TradingSession.LONDON: (ZoneInfo("Europe/London"), 8, 17),
    TradingSession.NEW_YORK: (NY, 8, 17),
}


class YahooForexProvider(MarketDataProvider):
    name = "yahoo"
    description = "Yahoo Finance public chart endpoint (Forex spot, no API key)"

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float | None = None) -> None:
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout or settings.provider_timeout_seconds
        self._health = ProviderHealth(provider=self.name, reachable=False)
        self._latencies: list[float] = []

    # ---------------------------------------------------------------- client
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Accept": "application/json,text/plain,*/*"},
                follow_redirects=True,
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # -------------------------------------------------------------- requests
    async def _fetch_chart(self, provider_symbol: str, interval: str, range_: str) -> dict:
        """GET the chart payload with retries, host/UA failover and health tracking."""
        client = await self._get_client()
        last_error: ProviderError | None = None

        for attempt in range(settings.provider_max_retries):
            host = HOSTS[attempt % len(HOSTS)]
            user_agent = USER_AGENTS[attempt % len(USER_AGENTS)]
            url = f"{host}/v8/finance/chart/{provider_symbol}"
            params = {"interval": interval, "range": range_}
            started = time.perf_counter()
            self._health.requests_total += 1

            try:
                response = await client.get(url, params=params, headers={"User-Agent": user_agent})
                latency = (time.perf_counter() - started) * 1000
                self._latencies.append(latency)
                self._latencies = self._latencies[-50:]
                self._health.average_latency_ms = round(sum(self._latencies) / len(self._latencies), 1)

                if response.status_code == 429:
                    raise ProviderRateLimited(f"upstream rate limit (HTTP 429) on {host}", retryable=True)
                if response.status_code >= 500:
                    raise ProviderUnavailable(
                        f"upstream server error (HTTP {response.status_code}) on {host}", retryable=True
                    )
                if response.status_code >= 400:
                    raise ProviderBadPayload(
                        f"upstream rejected request (HTTP {response.status_code})", retryable=False
                    )

                payload = response.json()
                error = (payload.get("chart") or {}).get("error")
                if error:
                    message = error.get("description") or error.get("code") or "unknown upstream error"
                    raise ProviderBadPayload(f"upstream error: {message}", retryable=False)

                self._mark_success()
                return payload

            except ProviderError as exc:
                if not exc.retryable:
                    self._mark_failure(exc)
                    logger.error(
                        "Provider rejected the request (%s %s %s): %s", provider_symbol, interval, range_, exc
                    )
                    raise
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeout(f"timeout after {self._timeout}s on {host}", cause=exc)
            except httpx.HTTPError as exc:
                last_error = ProviderUnavailable(f"network failure on {host}", cause=exc)
            except Exception as exc:  # JSON decode / unexpected shape
                last_error = ProviderBadPayload(f"malformed upstream payload from {host}", cause=exc)

            self._mark_failure(last_error)
            logger.warning(
                "Provider request failed (attempt %s/%s, %s %s %s): %s (cause: %s)",
                attempt + 1,
                settings.provider_max_retries,
                provider_symbol,
                interval,
                range_,
                last_error,
                type(last_error.cause).__name__ if getattr(last_error, "cause", None) else "n/a",
            )
            if attempt < settings.provider_max_retries - 1:
                await asyncio.sleep(settings.provider_backoff_seconds * (2**attempt))

        if last_error is None:  # pragma: no cover - defensive
            raise ProviderUnavailable("provider request failed without a recorded cause")
        raise last_error

    def _mark_success(self) -> None:
        self._health.reachable = True
        self._health.last_success_utc = datetime.now(tz=timezone.utc)
        self._health.consecutive_failures = 0

    def _mark_failure(self, error: BaseException) -> None:
        self._health.reachable = False
        self._health.last_error_utc = datetime.now(tz=timezone.utc)
        self._health.last_error = str(error)[:300]
        self._health.consecutive_failures += 1
        self._health.requests_failed += 1

    # ------------------------------------------------------------------ API
    async def get_symbols(self) -> list[SymbolInfo]:
        infos: list[SymbolInfo] = []
        for code in settings.symbol_list:
            info = get_symbol_info(code)
            if info is None:
                logger.warning("Symbol %s is in WATCHLIST but absent from the instrument catalog", code)
                continue
            infos.append(info)
        return infos

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        limit: int = 400,
    ) -> CandleSeries:
        code = normalize_symbol(symbol)
        info = get_symbol_info(code)
        if info is None:
            raise UnknownSymbol(f"symbol '{code}' is not in the instrument catalog")

        try:
            tf = as_timeframe(timeframe)
        except ValueError as exc:
            raise UnsupportedTimeframe(f"timeframe '{timeframe}' is not supported", cause=exc) from exc

        limit = max(10, min(int(limit), settings.max_candles_per_request))
        interval = INTERVAL_MAP[tf]
        range_ = self._pick_range(tf, limit)

        payload = await self._fetch_chart(info.provider_symbol, interval, range_)
        result = (payload.get("chart") or {}).get("result")
        if not result:
            raise ProviderBadPayload(f"empty chart result for {code} {tf.value}")
        block = result[0]

        timestamps = block.get("timestamp") or []
        quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
        opens, highs, lows, closes = (
            quote.get("open") or [],
            quote.get("high") or [],
            quote.get("low") or [],
            quote.get("close") or [],
        )
        volumes = quote.get("volume") or []

        if not timestamps or not closes:
            raise ProviderBadPayload(f"no OHLC series in payload for {code} {tf.value}")

        now = datetime.now(tz=timezone.utc)
        now_ts = int(now.timestamp())
        tf_seconds = tf.seconds

        rows: list[tuple[int, float, float, float, float, float | None]] = []
        dropped_null = 0
        dropped_future = 0
        tf_tolerance = 60  # tolerate a few seconds of clock skew

        for i, ts in enumerate(timestamps):
            if ts is None:
                dropped_null += 1
                continue
            ts = int(ts)
            if ts > now_ts + tf_tolerance:
                dropped_future += 1
                continue
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None  # noqa: E741
            c = closes[i] if i < len(closes) else None
            if None in (o, h, l, c):
                dropped_null += 1
                continue
            try:
                values = (float(o), float(h), float(l), float(c))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                dropped_null += 1
                continue
            if min(values) <= 0 or max(values) != max(values):
                dropped_null += 1
                continue
            volume = None
            if i < len(volumes) and volumes[i] is not None:
                try:
                    volume = float(volumes[i])
                except (TypeError, ValueError):
                    volume = None
            rows.append((ts, *values, volume))

        if not rows:
            raise ProviderBadPayload(f"no usable OHLC bars for {code} {tf.value}")

        quality_warnings: list[str] = []
        # Daily bars keep the exchange midnight (which shifts with DST): no snapping.
        tolerance = 5 if tf_seconds < 86400 else 0
        rows, alignment_notes = self._align_to_grid(rows, tf_seconds, tf, tolerance_seconds=tolerance)
        quality_warnings.extend(alignment_notes)

        window_rows = rows[-limit:]
        if dropped_future:
            quality_warnings.append(f"{dropped_future} future bar(s) discarded")
            logger.warning("Discarded %s future bar(s) for %s %s", dropped_future, code, tf.value)

        window_start = window_rows[0][0]
        nulls_in_window = self._count_nulls_in_window(timestamps, opens, window_start)
        if nulls_in_window:
            quality_warnings.append(
                f"{nulls_in_window} incomplete source bar(s) inside the returned window "
                "(weekend / holiday gaps)"
            )

        candles = [
            Candle(
                time=row[0],
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
                closed=(now_ts >= row[0] + tf_seconds),
            )
            for row in window_rows
        ]

        return CandleSeries(
            symbol=code,
            timeframe=tf,
            provider=self.name,
            candles=candles,
            fetched_at=now,
            data_state=DataState.CONNECTED,
            stale=False,
            quality_warnings=quality_warnings,
        )

    @staticmethod
    def _align_to_grid(
        rows: list[tuple[int, float, float, float, float, float | None]],
        tf_seconds: int,
        tf: Timeframe,
        tolerance_seconds: int = 5,
    ) -> tuple[list[tuple[int, float, float, float, float, float | None]], list[str]]:
        """Align the upstream series on the timeframe grid.

        Measured upstream behaviour (2026-09-29 / 2026-09-30): the feed returns
        bars on a clean grid (23:00:00, 23:15:00, ...) plus a *partial* bar
        stamped with the current second (23:04:59) covering the period that is
        still running. On the daily series that running bar is the only one for
        its period and carries "now" (e.g. 00:19:43 instead of the exchange
        midnight 23:00:00). Some bars also arrive with a 1-second offset
        (23:05:01), and the daily series carries the exchange midnight, which
        shifts by one hour at DST.

        Rules - no price is ever invented, only the newest real values are kept:
        1. a bar within ``tolerance_seconds`` of a grid point is snapped onto it;
        1b. a bar that started less than one timeframe ago (its period is still
           running, so it cannot be closed) is re-stamped on its period start:
           the OHLC values are the upstream ones, only the stamp is aligned;
        2. two bars whose start differs by less than one timeframe belong to the
           same period and are folded together: first open, highest high, lowest
           low, last close, summed volume.
        Every transformation is reported in ``CandleSeries.quality_warnings``.
        """
        notes: list[str] = []
        if not rows:
            return rows, notes

        anchor = rows[0][0]
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        aligned: list[tuple[int, float, float, float, float, float | None]] = []
        snapped = 0
        running_realigned = 0
        offgrid_timestamps: list[int] = []

        for index, row in enumerate(rows):
            ts = row[0]
            delta = (ts - anchor) % tf_seconds
            is_running_bar = index == len(rows) - 1 and 0 <= now_ts - ts < tf_seconds

            if delta == 0:
                aligned.append(row)
                continue
            if tolerance_seconds <= 0:
                # Daily series: the only tolerated move is the running bar, which
                # upstream stamps with "now" instead of the exchange midnight.
                if is_running_bar and delta < tf_seconds:
                    aligned.append((ts - delta, *row[1:]))
                    running_realigned += 1
                else:
                    aligned.append(row)
                    offgrid_timestamps.append(ts)
                continue
            if delta <= tolerance_seconds:
                aligned.append((ts - delta, *row[1:]))
                snapped += 1
            elif tf_seconds - delta <= tolerance_seconds:
                aligned.append((ts + (tf_seconds - delta), *row[1:]))
                snapped += 1
            elif is_running_bar and delta < tf_seconds:
                # The period is still running: the bar cannot be closed, so its
                # stamp (the current second) is aligned on the period start.
                aligned.append((ts - delta, *row[1:]))
                running_realigned += 1
            else:
                # Genuinely off-grid bar (e.g. a mid-period partial bar): kept
                # unchanged here, folded by rule 2 below when it belongs to the
                # period of the previous bar.
                aligned.append(row)
                offgrid_timestamps.append(ts)

        merged: dict[int, tuple[int, float, float, float, float, float | None]] = {}
        order: list[int] = []
        folded = 0
        for row in aligned:
            if order and (row[0] - order[-1]) < tf_seconds:
                key = order[-1]
                current = merged[key]
                volume = None
                if current[5] is not None or row[5] is not None:
                    volume = (current[5] or 0.0) + (row[5] or 0.0)
                merged[key] = (
                    key,
                    current[1],
                    max(current[2], row[2]),
                    min(current[3], row[3]),
                    row[4],
                    volume,
                )
                folded += 1
            else:
                order.append(row[0])
                merged[row[0]] = row

        result = [merged[key] for key in order]

        if snapped:
            notes.append(
                f"{snapped} bar(s) snapped onto the {tf.value} grid "
                f"(source offset <= {tolerance_seconds}s, prices unchanged)"
            )
        if folded:
            notes.append(
                f"{folded} partial bar(s) folded into the running {tf.value} bar "
                "(newest close kept, high/low extended)"
            )
        if running_realigned:
            notes.append(
                f"{running_realigned} running bar(s) re-stamped on their {tf.value} period start "
                "(upstream stamps the in-progress bar with the current time; prices unchanged)"
            )
        offgrid_remaining = sum(1 for ts in offgrid_timestamps if ts in merged)
        if offgrid_remaining and tf_seconds < 86400:
            notes.append(
                f"{offgrid_remaining} bar(s) could not be aligned to the {tf.value} grid - kept unchanged"
            )
        return result, notes

    @staticmethod
    def _count_nulls_in_window(timestamps: list, opens: list, window_start: int) -> int:
        count = 0
        for i, ts in enumerate(timestamps):
            if ts is None or int(ts) < window_start:
                continue
            if i >= len(opens) or opens[i] is None:
                count += 1
        return count

    def _pick_range(self, tf: Timeframe, limit: int) -> str:
        for range_, capacity in RANGE_LADDER[tf]:
            if capacity >= limit:
                return range_
        return RANGE_LADDER[tf][-1][0]

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe | str) -> Candle:
        series = await self.get_candles(symbol, timeframe, limit=10)
        return series.candles[-1]

    async def get_quote(self, symbol: str, timeframe: Timeframe | str) -> tuple[float | None, int | None]:
        """Use the upstream ``meta`` block: it carries the live quote timestamp."""
        code = normalize_symbol(symbol)
        info = get_symbol_info(code)
        if info is None:
            raise UnknownSymbol(f"symbol '{code}' is not in the instrument catalog")
        tf = as_timeframe(timeframe)
        payload = await self._fetch_chart(info.provider_symbol, INTERVAL_MAP[tf], self._pick_range(tf, 60))
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None, None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        ts = meta.get("regularMarketTime")
        if price is None:
            return None, None
        return float(price), int(ts) if ts else None

    async def get_market_status(self, now: datetime | None = None) -> MarketStatus:
        """Forex session state derived from the clock (weekend-aware).

        The holiday calendar is intentionally NOT implemented (Phase 1): the
        status reports OPEN/CLOSED from the weekly schedule only.
        """
        now = now or datetime.now(tz=timezone.utc)
        ny_now = now.astimezone(NY)
        weekday = ny_now.weekday()  # 0 = Monday
        close_hour = 17

        def at_ny_hour(day_offset: int, hour: int) -> datetime:
            base = (ny_now + timedelta(days=day_offset)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            return base.astimezone(timezone.utc)

        is_open = False
        phase = MarketPhase.OPEN
        note = "Weekly schedule: opens Sunday 17:00 ET, closes Friday 17:00 ET. Holiday calendar not implemented."
        next_open: datetime | None = None
        next_close: datetime | None = None

        if weekday == 5:  # Saturday
            phase, is_open = MarketPhase.CLOSED_WEEKEND, False
            next_open = at_ny_hour(1, close_hour)  # Sunday 17:00 ET
        elif weekday == 6:  # Sunday
            if ny_now.hour < close_hour:
                phase, is_open = MarketPhase.CLOSED_WEEKEND, False
                next_open = at_ny_hour(0, close_hour)
            else:
                is_open = True
                next_close = at_ny_hour(5 - weekday, close_hour)
        elif weekday == 4:  # Friday
            if ny_now.hour >= close_hour:
                phase, is_open = MarketPhase.CLOSED_WEEKEND, False
                next_open = at_ny_hour(2, close_hour)  # Sunday 17:00 ET
            else:
                is_open = True
                next_close = at_ny_hour(0, close_hour)
        else:
            is_open = True
            next_close = at_ny_hour(4 - weekday, close_hour)

        sessions: list[TradingSession] = []
        if is_open:
            for session, (zone, start, end) in SESSION_ZONES.items():
                local = now.astimezone(zone)
                if local.weekday() >= 5:
                    continue
                if start <= local.hour < end:
                    sessions.append(session)

        return MarketStatus(
            phase=phase,
            is_open=is_open,
            active_sessions=sessions,
            reference_time_utc=now,
            next_open_utc=next_open,
            next_close_utc=next_close,
            note=note,
        )

    async def health(self) -> ProviderHealth:
        return self._health.model_copy(deep=True)


class DisabledProvider(MarketDataProvider):
    """Provider used when MARKET_DATA_PROVIDER=disabled.

    It never returns a price: the UI then shows DATA UNAVAILABLE, which is the
    correct behaviour for an environment without a live feed.
    """

    name = "disabled"
    description = "No live market data source configured"

    async def get_symbols(self) -> list[SymbolInfo]:
        return [info for code in settings.symbol_list if (info := get_symbol_info(code))]

    async def get_candles(self, symbol: str, timeframe: Timeframe | str, limit: int = 400) -> CandleSeries:
        raise ProviderDisabled("market data provider is disabled (MARKET_DATA_PROVIDER=disabled)")

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe | str) -> Candle:
        raise ProviderDisabled("market data provider is disabled (MARKET_DATA_PROVIDER=disabled)")

    async def get_quote(self, symbol: str, timeframe: Timeframe | str) -> tuple[float | None, int | None]:
        return None, None

    async def get_market_status(self, now: datetime | None = None) -> MarketStatus:
        return MarketStatus(
            phase=MarketPhase.UNKNOWN,
            is_open=False,
            reference_time_utc=datetime.now(tz=timezone.utc),
            note="PROVIDER DISABLED - no market data available",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, reachable=False, last_error="provider disabled")
