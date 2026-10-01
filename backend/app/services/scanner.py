"""Background market scanner.

Every tick it reads each watched pair from the real provider, derives the
Phase-1 structure, persists the bars/events and publishes the resulting events
on the event bus (which feeds WebSocket and SSE).

Rules enforced here:
* no invented price: a failing pair is reported with ``data_state=DATA_UNAVAILABLE``;
* the chartist engine runs once per CLOSED bar (never on a forming bar) and its
  findings are published as PATTERN_* / BREAKOUT_* / RETEST_* events;
* the scan is skipped while the market is closed (status from the provider clock).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import settings
from app.db.repository import EventRepository, ScannerRunRepository
from app.logging_conf import get_logger
from app.providers.errors import ProviderError
from app.schemas.events import EventType, MarketEvent
from app.schemas.market import DataState, as_timeframe
from app.confluence.engine import OBSERVED_STATES
from app.services.confluence import ConfluenceService
from app.capture.service import CaptureService
from app.services.opportunities import OpportunityService
from app.services.events import EventBus, event_bus
from app.services.market_service import MarketService
from app.services.patterns import PatternService
from app.services.price_action import PriceActionService
from app.services.smc_ict import SmcIctService
from app.services.structure import analyse_structure, recent_labels

logger = get_logger(__name__)


class MarketScanner:
    def __init__(
        self,
        market_service: MarketService | None = None,
        bus: EventBus | None = None,
        event_repository: EventRepository | None = None,
        run_repository: ScannerRunRepository | None = None,
        pattern_service: PatternService | None = None,
        price_action_service: PriceActionService | None = None,
        smc_ict_service: SmcIctService | None = None,
        confluence_service: ConfluenceService | None = None,
        opportunity_service: OpportunityService | None = None,
        capture_service: CaptureService | None = None,
    ) -> None:
        self.market = market_service or MarketService()
        self.bus = bus or event_bus
        self.events_repo = event_repository or EventRepository()
        self.runs_repo = run_repository or ScannerRunRepository()
        self.patterns = pattern_service or PatternService(bus=self.bus)
        self.price_action = price_action_service or PriceActionService(bus=self.bus)
        self.smc_ict = smc_ict_service or SmcIctService(bus=self.bus)
        self.confluence = confluence_service or ConfluenceService(bus=self.bus)
        self.opportunities = opportunity_service or OpportunityService(bus=self.bus)
        self.capture = capture_service

        self.running = False
        self._task: asyncio.Task | None = None
        self.last_tick_at: datetime | None = None
        self.last_tick_duration_ms: float | None = None
        self.ticks = 0
        self.pairs_ok = 0
        self.pairs_failed = 0
        self.last_errors: list[str] = []
        #: (symbol, timeframe) -> open time of the last closed bar seen
        self._last_closed: dict[tuple[str, str], int] = {}
        #: (symbol, timeframe) -> last published structure trend
        self._last_trend: dict[tuple[str, str], str] = {}

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="smv-scanner")
        logger.info(
            "Scanner started (tick=%ss, pairs=%s, timeframe=%s)",
            settings.scanner_tick_seconds,
            len(settings.symbol_list),
            settings.scanner_default_timeframe,
        )

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover - expected
                pass
            self._task = None
        logger.info("Scanner stopped")

    async def _loop(self) -> None:
        # small delay so the API can finish booting before the first upstream call
        await asyncio.sleep(1.0)
        while self.running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the scanner must never die silently
                logger.exception("Scanner tick crashed: %s", exc)
            await asyncio.sleep(max(5, settings.scanner_tick_seconds))

    # ---------------------------------------------------------------- tick
    async def tick(self) -> dict:
        started = asyncio.get_running_loop().time()
        self.last_tick_at = datetime.now(tz=timezone.utc)
        self.ticks += 1

        market_status = await self.market.get_market_status()
        symbols = settings.symbol_list

        # Only scan the pairs the UI currently needs, plus everything when
        # SCANNER_WATCH_ALL is on (default) so history keeps building.
        targets = symbols if settings.scanner_watch_all else await self._active_symbols()

        run_id = self._safe_run_start()
        ok = failed = 0
        errors: list[str] = []

        for symbol in targets:
            for timeframe in self._timeframes_for(symbol):
                try:
                    await self._scan_pair(symbol, timeframe, market_status.is_open)
                    ok += 1
                except ProviderError as exc:
                    failed += 1
                    message = f"{symbol} {timeframe}: {exc.code} - {exc.message}"
                    errors.append(message)
                    logger.warning("Scan failed for %s: %s", symbol, exc)
                    self.bus.publish_nowait(
                        MarketEvent(
                            event_type=EventType.PROVIDER_STATUS,
                            symbol=symbol,
                            timeframe=as_timeframe(timeframe),
                            metadata={
                                "data_state": DataState.DATA_UNAVAILABLE.value,
                                "provider": self.market.provider_name,
                                "error_code": exc.code,
                                "error": exc.message,
                            },
                            source="SCANNER",
                        )
                    )
                except Exception as exc:  # unexpected: keep the loop alive
                    failed += 1
                    errors.append(f"{symbol} {timeframe}: {type(exc).__name__} - {exc}")
                    logger.exception("Unexpected scan error for %s %s", symbol, timeframe)

        self.pairs_ok = ok
        self.pairs_failed = failed
        self.last_errors = errors[:10]
        self.last_tick_duration_ms = round((asyncio.get_running_loop().time() - started) * 1000, 1)

        if run_id is not None:
            try:
                self.runs_repo.finish(run_id, ok, failed, errors)
            except Exception as exc:  # pragma: no cover - persistence best effort
                logger.error("Could not close scanner run %s: %s", run_id, exc)

        self.bus.publish_nowait(
            MarketEvent(
                event_type=EventType.SYSTEM_STATUS,
                metadata={
                    "scanner": "RUNNING" if self.running else "STOPPED",
                    "pairs_scanned": ok,
                    "pairs_failed": failed,
                    "market_open": market_status.is_open,
                    "duration_ms": self.last_tick_duration_ms,
                    "subscribers": self.bus.subscriber_count,
                },
                source="SCANNER",
            )
        )
        return {
            "pairs_scanned": ok,
            "pairs_failed": failed,
            "duration_ms": self.last_tick_duration_ms,
            "errors": errors[:5],
        }

    async def _scan_pair(self, symbol: str, timeframe: str, market_open: bool) -> None:
        series = await self.market.get_candles(symbol, timeframe, limit=settings.scanner_bars)
        last = series.last_candle
        if last is None:
            return

        closed = series.closed_candles
        last_closed = closed[-1] if closed else None
        key = (symbol, as_timeframe(timeframe).value)

        structure = analyse_structure(symbol, timeframe, series.candles)
        labels = recent_labels(structure, 4)

        prev_close = closed[-2].close if len(closed) >= 2 else None
        change_percent = None
        if prev_close:
            change_percent = round((last.close - prev_close) / prev_close * 100, 4)

        self.bus.publish_nowait(
            MarketEvent(
                event_type=EventType.MARKET_UPDATE,
                symbol=symbol,
                timeframe=as_timeframe(timeframe),
                price=last.close,
                metadata={
                    "data_state": series.data_state.value,
                    "provider": series.provider,
                    "market_open": market_open,
                    "candle_time": last.opened_at.isoformat(),
                    "candle_closed": last.closed,
                    "change_percent": change_percent,
                    "stale": series.stale,
                    "structure_trend": structure.trend.value,
                    "structure_labels": labels,
                    "quality_warnings": series.quality_warnings,
                },
                source="SCANNER",
            )
        )

        if last_closed is not None:
            previous_seen = self._last_closed.get(key)
            first_observation = previous_seen is None
            if first_observation:
                self._last_closed[key] = last_closed.time
            if first_observation or (previous_seen is not None and last_closed.time > previous_seen):
                self._last_closed[key] = last_closed.time
                closed_series = series.model_copy(
                    update={"candles": [c for c in series.candles if c.time <= last_closed.time]}
                )
                closed_structure = analyse_structure(symbol, timeframe, closed_series.candles)
                self.bus.publish_nowait(
                    MarketEvent(
                        event_type=EventType.CANDLE_CLOSED,
                        symbol=symbol,
                        timeframe=as_timeframe(timeframe),
                        price=last_closed.close,
                        metadata={
                            "candle_time": last_closed.opened_at.isoformat(),
                            "open": last_closed.open,
                            "high": last_closed.high,
                            "low": last_closed.low,
                            "close": last_closed.close,
                            "structure_trend": closed_structure.trend.value,
                        },
                        source="SCANNER",
                    )
                )
                self._persist_event(
                    EventType.CANDLE_CLOSED,
                    symbol,
                    as_timeframe(timeframe).value,
                    last_closed.close,
                    {"candle_time": last_closed.opened_at.isoformat()},
                )
                # chartist engine: one pass per closed bar, on closed candles only
                self._run_patterns(series, closed, symbol, as_timeframe(timeframe).value)

        trend_key = structure.trend.value
        if self._last_trend.get(key) != trend_key:
            self._last_trend[key] = trend_key
            self.bus.publish_nowait(
                MarketEvent(
                    event_type=EventType.STRUCTURE_UPDATE,
                    symbol=symbol,
                    timeframe=as_timeframe(timeframe),
                    price=last.close,
                    metadata={
                        "trend": structure.trend.value,
                        "labels": labels,
                        "swings": len(structure.swings),
                        "notes": structure.notes,
                    },
                    source="STRUCTURE_ENGINE",
                )
            )

    def _run_patterns(self, series, closed_candles, symbol: str, timeframe: str) -> None:
        """Chartist engine on the closed candles of this series (never a live bar)."""
        window = self.patterns.params.globals.window_bars
        candles = list(closed_candles)[-window:]
        if len(candles) < self.patterns.params.globals.min_bars_required:
            return
        engine_series = series.model_copy(update={"candles": candles})
        result = self.patterns.analyse(engine_series)
        if result.detections:
            logger.info(
                "Pattern engine %s %s: %s detection(s) from %s bars in %sms",
                symbol,
                timeframe,
                len(result.detections),
                result.bars_analyzed,
                result.duration_ms,
            )
        # Price-action engine: same closed bar, and it consumes the chartist state
        # (real levels + confirmed breakouts) instead of recomputing them.
        self._run_price_action(series, closed_candles, symbol, timeframe)
        # SMC/ICT engine: same closed bar, no second pivot engine, no second bus.
        self._run_smc_ict(series, closed_candles, symbol, timeframe)
        # Confluence engine: it CONSUMES what the three engines just published
        # (it never recomputes a detection, never invents an event).
        self._run_confluence(series, closed_candles, symbol, timeframe)

    def _run_price_action(self, series, closed_candles, symbol: str, timeframe: str) -> None:
        """Price-action engine on the closed candles of this series (never a live bar)."""
        globals_ = self.price_action.params.globals
        candles = list(closed_candles)[-globals_.window_bars :]
        if len(candles) < globals_.min_bars_required:
            return
        engine_series = series.model_copy(update={"candles": candles})
        chartist = self.patterns.tracked(symbol=symbol, timeframe=timeframe)
        result = self.price_action.analyse(engine_series, chartist=chartist)
        if result.detections:
            logger.info(
                "Price-action engine %s %s: %s detection(s) from %s bars in %sms",
                symbol,
                timeframe,
                len(result.detections),
                result.bars_analyzed,
                result.duration_ms,
            )

    def _run_confluence(self, series, closed_candles, symbol: str, timeframe: str) -> None:
        """Confluence on the closed candles, from the three engines' live state.

        The three engines are read, never modified: the confluence consumes the
        detections they already track for this pair / timeframe, plus the tracked
        detections of the slower timeframes as *context* (each one keeps its own
        timeframe label in the score).
        """
        confluence_params = self.confluence.params()
        globals_ = confluence_params.global_
        candles = list(closed_candles)[-max(globals_.min_bars_required, 300) :]
        if len(candles) < globals_.min_bars_required:
            return
        engine_series = series.model_copy(update={"candles": candles})

        detections = (
            self.patterns.tracked(symbol=symbol, timeframe=timeframe)
            + self.price_action.tracked(symbol=symbol, timeframe=timeframe)
            + self.smc_ict.tracked(symbol=symbol, timeframe=timeframe)
        )

        context: dict[str, list] = {}
        if confluence_params.multi_timeframe.enabled:
            current_seconds = as_timeframe(timeframe).seconds
            slower = [
                candidate
                for candidate in confluence_params.multi_timeframe.higher_timeframes
                if as_timeframe(candidate).seconds > current_seconds
            ][: confluence_params.multi_timeframe.context_timeframes]
            for context_timeframe in slower:
                items = (
                    self.patterns.tracked(symbol=symbol, timeframe=context_timeframe)
                    + self.price_action.tracked(symbol=symbol, timeframe=context_timeframe)
                    + self.smc_ict.tracked(symbol=symbol, timeframe=context_timeframe)
                )
                if items:
                    context[context_timeframe] = items

        try:
            result = self.confluence.analyse(engine_series, detections, context=context)
        except Exception as exc:  # never let the confluence stop the scan
            logger.exception("Confluence step failed for %s %s: %s", symbol, timeframe, exc)
            return
        if result.groups:
            try:
                opportunities = self._run_opportunities(engine_series, result.groups, symbol, timeframe)
            except Exception as exc:  # the opportunity step must never stop the scan either
                logger.exception("Opportunity step failed for %s %s: %s", symbol, timeframe, exc)
            else:
                self._request_capture(engine_series, detections, result, opportunities, symbol, timeframe)
        if result.groups:
            observed = [group for group in result.groups if group.state in OBSERVED_STATES]
            logger.info(
                "Confluence %s %s: %s group(s) from %s event(s) in %sms%s",
                symbol,
                timeframe,
                len(result.groups),
                result.events_considered,
                result.duration_ms,
                f" - observed: {', '.join(f'{g.state}/{g.direction}/{g.score:g}' for g in observed)}"
                if observed
                else "",
            )

    def _run_opportunities(self, series, groups, symbol: str, timeframe: str) -> None:
        """Opportunity step: reads the confluences, never recomputes anything.

        Only the confluences that describe a direction are handed over; a neutral or
        empty context would produce nothing but noise.
        """
        # every tick: the lifecycle (confirmation, weakening, expiration) is part of
        # the observation, so the engine also runs when no new confluence appeared.
        result = self.opportunities.analyse(series, list(groups))
        if result.opportunities:
            logger.info(
                "Opportunity engine %s %s: %s observation(s) from %s confluence(s) in %sms - %s",
                symbol,
                timeframe,
                len(result.opportunities),
                result.confluences_considered,
                result.duration_ms,
                ", ".join(
                    f"{item.direction}/{item.state}/{item.score:g}"
                    for item in result.opportunities[:3]
                ),
            )
        return result

    def _request_capture(self, series, detections, confluence_result, opportunities, symbol: str, timeframe: str) -> None:
        """Ask for a chart capture of the strongest observation.

        The call only queues a job (Phase 7 renders it in a worker thread): the
        scanner never waits for an image, and a capture failure never affects the
        market stream.
        """
        if self.capture is None or not self.capture.params.enabled:
            return
        if opportunities is None or not opportunities.opportunities:
            return
        priority = {"CONFIRMED": 0, "CREATED": 1, "ACTIVE": 2, "WEAKENED": 3}
        candidates = [item for item in opportunities.opportunities if item.direction in ("BUY", "SELL", "WATCH")]
        if not candidates:
            return
        best = sorted(candidates, key=lambda item: (priority.get(item.state, 9), -item.score))[0]
        confluence_id = best.confluence_id
        groups = [group for group in confluence_result.groups if group.id == confluence_id] or list(confluence_result.groups)
        requested = self.capture.request(
            series,
            detections=detections,
            confluences=groups,
            opportunity=best,
            timeframe=timeframe,
        )
        if requested:
            logger.info("Capture queued for %s %s: %s (%s)", symbol, timeframe, requested, best.direction)

    def _run_smc_ict(self, series, closed_candles, symbol: str, timeframe: str) -> None:
        """SMC/ICT engine on the closed candles of this series (never a live bar)."""
        globals_ = self.smc_ict.params.global_
        candles = list(closed_candles)[-globals_.window_bars :]
        if len(candles) < globals_.min_bars_required:
            return
        engine_series = series.model_copy(update={"candles": candles})
        result = self.smc_ict.analyse(engine_series)
        if result.detections:
            logger.info(
                "SMC/ICT engine %s %s: %s object(s) from %s bars in %sms",
                symbol,
                timeframe,
                len(result.detections),
                result.bars_analyzed,
                result.duration_ms,
            )
        for warning in result.warnings:
            logger.warning("SMC/ICT %s %s: %s", symbol, timeframe, warning)

    # -------------------------------------------------------------- helpers
    def _timeframes_for(self, symbol: str) -> list[str]:
        """Scanner cadence: fast timeframe always, MTF ladder for the selected pair."""
        base = [settings.scanner_default_timeframe.upper()]
        if symbol == (settings.symbol_list[0] if settings.symbol_list else None):
            base = list(dict.fromkeys(["M15", "H1", "H4", "D1"]))
        return base

    async def _active_symbols(self) -> list[str]:
        return settings.symbol_list

    def _persist_event(
        self, event_type: EventType, symbol: str, timeframe: str, price: float | None, metadata: dict
    ) -> None:
        try:
            self.events_repo.save(
                MarketEvent(
                    event_type=event_type,
                    symbol=symbol,
                    timeframe=as_timeframe(timeframe),
                    price=price,
                    metadata=metadata,
                    source="SCANNER",
                )
            )
        except Exception as exc:  # pragma: no cover - persistence best effort
            logger.error("Could not persist event: %s", exc)

    def _safe_run_start(self) -> int | None:
        try:
            return self.runs_repo.start(self.market.provider_name)
        except Exception as exc:  # pragma: no cover
            logger.error("Could not record scanner run: %s", exc)
            return None

    def status(self) -> dict:
        return {
            "running": self.running,
            "ticks": self.ticks,
            "interval_seconds": settings.scanner_tick_seconds,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_tick_duration_ms": self.last_tick_duration_ms,
            "pairs_scanned_last_tick": self.pairs_ok,
            "pairs_failed_last_tick": self.pairs_failed,
            "errors": self.last_errors,
            "watch_all": settings.scanner_watch_all,
            "default_timeframe": settings.scanner_default_timeframe,
        }
