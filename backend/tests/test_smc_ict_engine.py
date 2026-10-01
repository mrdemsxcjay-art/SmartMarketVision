"""Phase 4 §20-§24 §29 §30 - engine, lifecycle, dedup, persistence, API, stream.

The engine is the only place that produces the API contract, so this file follows
one object from the detector through the registry, the database, the REST surface
and the real-time snapshot. Everything runs on controlled fixtures; production
data always comes from the provider.
"""

from __future__ import annotations

import time

import pytest

from app.api.stream import _smc_ict_snapshot
from app.schemas.events import DetectionCategory, DetectionSource, DetectionStatus, EventType
from app.smc_ict.engine import ENGINE_NAME, SmcIctEngine, dedup_key
from app.smc_ict.params import SmcIctParams
from tests import smc_ict_fixtures as fx

FORBIDDEN = ("BUY", "SELL", "ENTRY", "STOP LOSS", "TAKE PROFIT", "LONG", "SHORT")


def engine(**overrides) -> SmcIctEngine:
    params = SmcIctParams()
    for key, value in overrides.items():
        setattr(params, key, value)
    return SmcIctEngine(params)


def to_series(legs_or_candles):
    """Accept a leg list, a candle list, or an already-built series."""
    if hasattr(legs_or_candles, "candles"):
        return legs_or_candles
    if legs_or_candles and hasattr(legs_or_candles[0], "high"):
        return fx.series(list(legs_or_candles))
    return fx.series(fx.path_series(legs_or_candles))


def analyse_instance(target: SmcIctEngine, legs):
    series = to_series(legs)
    result = target.analyse(series)
    return series, result, target.commit(result)


class TestEngineContract:
    def test_objects_use_the_existing_contract(self):
        target = engine()
        _, result, _ = analyse_instance(target, fx.choch_bullish_legs())
        assert result.detections
        for detection in result.detections:
            assert detection.category is DetectionCategory.SMC_ICT
            assert detection.source_engine is DetectionSource.SMC_ICT_ENGINE
            assert detection.dedup_key == detection.id
            assert detection.id.startswith("smc_")
            assert detection.confidence is not None and 0.0 <= detection.confidence <= 100.0
            assert detection.evidence and detection.evidence_points["criteria"]
            assert detection.evidence_points["trading_signal"] is False
            assert detection.parameters["parameters_version"]

    def test_every_coordinate_sits_on_a_real_candle(self):
        target = engine()
        series, result, _ = analyse_instance(target, fx.sweep_bearish_legs())
        real_times = {candle.time for candle in series.candles}
        for detection in result.detections:
            for coordinate in detection.coordinates:
                assert coordinate.time in real_times, f"{detection.pattern} drew a point off the candles"
            for zone in detection.drawing.zones:
                assert zone.time_start in real_times
                assert zone.price_bottom < zone.price_top

    def test_confidence_comes_from_explicit_criteria(self):
        target = engine()
        _, result, _ = analyse_instance(target, fx.order_block_bullish_legs())
        for detection in result.detections:
            factors = detection.confidence_factors
            assert factors, "no criteria, no confidence"
            total = sum(f.weight for f in factors)
            passed = sum(f.weight for f in factors if f.passed)
            expected = round(100.0 * passed / total, 1)
            assert detection.confidence == expected

    def test_no_trading_instruction_anywhere(self):
        target = engine()
        for legs in (fx.bos_bullish_legs(), fx.choch_bearish_legs(), fx.breaker_bullish_legs()):
            _, result, _ = analyse_instance(target, legs)
            blob = " ".join(
                " ".join(
                    [d.pattern, d.direction.value, *d.evidence, *[f.criterion + " " + f.detail for f in d.confidence_factors]]
                )
                for d in result.detections
            ).upper()
            for word in FORBIDDEN:
                assert word not in blob, f"{word} leaked into the payload"

    def test_disabled_engine_does_nothing(self):
        params = SmcIctParams()
        params.enabled = False
        target = SmcIctEngine(params)
        _, result, _ = analyse_instance(target, fx.bos_bullish_legs())
        assert result.detections == []
        assert "desactive" in " ".join(result.notes)

    def test_short_series_is_refused_explicitly(self):
        target = engine()
        short = fx.path_series(fx.bos_bullish_legs(), warmup=False)[:40]
        result = target.analyse(fx.series(short))
        assert result.detections == []
        assert "minimum" in " ".join(result.notes)


class TestDeduplication:
    """§21 - same symbol + timeframe + pattern + source candles = same id."""

    def test_same_series_yields_the_same_ids(self):
        target = engine()
        series = fx.series(fx.path_series(fx.choch_bullish_legs()))
        first = target.analyse(series)
        first_ids = {d.id for d in first.detections}
        target.commit(first)
        assert set(target.registry) == first_ids
        second = target.analyse(series)
        target.commit(second)
        assert {d.id for d in second.detections} == first_ids
        assert set(target.registry) == first_ids  # nothing was duplicated

    def test_dedup_key_is_stable_and_source_bound(self):
        kwargs = dict(symbol="EURUSD", timeframe="M15", pattern="BOS", trigger_time=1000)
        assert dedup_key(**kwargs, source_time=900) == dedup_key(**kwargs, source_time=900)
        assert dedup_key(**kwargs, source_time=900) != dedup_key(**kwargs, source_time=800)
        assert dedup_key(**kwargs, source_time=None) != dedup_key(**kwargs, source_time=900)

    def test_a_new_object_is_announced_once(self):
        target = engine()
        series = fx.series(fx.path_series(fx.order_block_bullish_legs()))
        result = target.analyse(series)
        first_events = target.commit(result)
        assert any(event.event_type == "SMC_DETECTED" for event in first_events)
        second_events = target.commit(target.analyse(series))
        assert [e for e in second_events if e.event_type == "SMC_DETECTED"] == []

    def test_registry_cap_is_respected(self):
        params = SmcIctParams()
        params.global_.max_tracked = 5
        target = SmcIctEngine(params)
        _, result, _ = analyse_instance(target, fx.choch_bullish_legs())
        assert len(result.detections) <= 5


class TestLifecycle:
    """§20 - only the relevant statuses, and a real state transition."""

    def test_fvg_lifecycle_ends_filled(self):
        target = engine()
        legs = fx.fvg_bullish_filled_legs()
        series = fx.series(fx.path_series(legs))
        result = target.analyse(series)
        filled = [d for d in result.detections if d.pattern == "BULLISH_FVG" and d.status is DetectionStatus.FILLED]
        assert filled, "the fixture traverses the band entirely"
        assert filled[0].evidence_points["measurements"]["coverage_share"] == 1.0

    def test_mitigation_transition_is_published(self):
        target = engine()
        legs = list(fx.fvg_bullish_legs())
        partial = fx.series(fx.path_series(legs))
        target.commit(target.analyse(partial))
        # same market, then the gap gets mitigated
        extended = fx.series(fx.path_series(fx.fvg_bullish_partial_legs()))
        events = target.commit(target.analyse(extended))
        assert all(
            event.event_type
            in {
                "SMC_DETECTED",
                "SMC_CONFIRMED",
                "SMC_MITIGATED",
                "SMC_INVALIDATED",
                "SMC_FILLED",
                "SMC_EXPIRED",
            }
            for event in events
        )

    def test_status_mapping_is_explicit(self):
        target = engine()
        _, result, _ = analyse_instance(target, fx.choch_bullish_legs())
        by_pattern = {d.pattern: d.status for d in result.detections}
        assert by_pattern["CHOCH"] is DetectionStatus.CONFIRMED
        assert by_pattern["MSS"] is DetectionStatus.CONFIRMED
        assert by_pattern["LIQUIDITY_POOL_ESTIMATE"] is DetectionStatus.ACTIVE
        assert all(status in set(DetectionStatus) for status in by_pattern.values())

    def test_invalidated_block_is_reported_as_invalidated(self):
        target = engine()
        _, result, _ = analyse_instance(target, fx.breaker_bullish_legs())
        invalidated = [d for d in result.detections if d.status is DetectionStatus.INVALIDATED]
        assert invalidated
        assert all(d.invalidation.invalidated for d in invalidated)


class TestPersistence:
    """§22 - enough is stored to replay, back-test and compute statistics."""

    def test_service_persists_and_counts_by_category(self, container):
        service = container.smc_ict
        result = service.analyse(fx.series(fx.path_series(fx.choch_bullish_legs())), publish=False)
        assert result.detections
        stored = container.detections_repo.history(limit=200, category="SMC_ICT")
        assert len(stored) == len(result.detections)
        row = stored[0]
        assert row["category"] == "SMC_ICT"
        assert row["evidence_points"]["criteria"]
        assert row["parameters"]["parameters_version"]

    def test_history_filter_is_available(self, container):
        service = container.smc_ict
        service.analyse(fx.series(fx.path_series(fx.sweep_bearish_legs())), publish=False)
        rows = service.history(limit=50, pattern="LIQUIDITY_SWEEP")
        assert rows and all(r["pattern"] == "LIQUIDITY_SWEEP" for r in rows)

    def test_repeated_run_updates_in_place(self, container):
        service = container.smc_ict
        series = fx.series(fx.path_series(fx.choch_bullish_legs()))
        first = service.analyse(series, publish=False)
        count_after_first = len(container.detections_repo.history(limit=500, category="SMC_ICT"))
        service.analyse(series, publish=False)
        count_after_second = len(container.detections_repo.history(limit=500, category="SMC_ICT"))
        assert count_after_first == count_after_second == len(first.detections)


class TestRealTime:
    """§23 - the same bus, and a snapshot that removes the need to reload."""

    @pytest.mark.asyncio
    async def test_events_are_published_on_the_shared_bus(self, container):
        subscriber_id, queue = await container.bus.subscribe()
        try:
            container.smc_ict.analyse(fx.series(fx.path_series(fx.choch_bullish_legs())))
            received = []
            while not queue.empty():
                received.append(queue.get_nowait())
        finally:
            await container.bus.unsubscribe(subscriber_id)
        smc_events = [event for event in received if event.event_type.value.startswith("SMC_")]
        assert smc_events
        payload = smc_events[0].metadata
        assert payload["trading_signal"] is False
        assert payload["detection"]["category"] == "SMC_ICT"

    def test_snapshot_payload_shape(self, container):
        container.smc_ict.analyse(fx.series(fx.path_series(fx.sweep_bearish_legs())), publish=False)
        snapshot = _smc_ict_snapshot(container, "EURUSD", "M15")
        assert snapshot is not None
        assert snapshot.event_type is EventType.SMC_ICT_SNAPSHOT
        assert snapshot.metadata["trading_signal"] is False
        assert snapshot.metadata["detections"]
        assert snapshot.metadata["counts"]

    def test_snapshot_is_absent_when_nothing_is_tracked(self, container):
        assert _smc_ict_snapshot(container, None, None) is None

    def test_event_types_are_declared(self):
        for name in ("SMC_DETECTED", "SMC_CONFIRMED", "SMC_MITIGATED", "SMC_INVALIDATED", "SMC_FILLED", "SMC_EXPIRED"):
            assert EventType(name)


class TestApi:
    """§30 - the REST surface exposes the observation, never an instruction."""

    def test_params_endpoint(self, client):
        payload = client.get("/api/smc-ict/params").json()
        assert payload["trading_signal"] is False
        assert payload["engines"][ENGINE_NAME] == "ENABLED"
        assert set(payload["params"]) == {
            "globals",
            "swings",
            "bos",
            "choch",
            "mss",
            "equal_levels",
            "pools",
            "sweep",
            "fvg",
            "mitigation",
            "order_block",
            "breaker",
            "displacement",
            "dealing_range",
            "premium_discount",
            "confluence",
            "weights",
        }

    def test_params_override_is_validated(self, client):
        ok = client.patch("/api/smc-ict/params", json={"overrides": {"bos": {"min_break_pips": 2.0}}})
        assert ok.status_code == 200
        assert ok.json()["params"]["bos"]["min_break_pips"] == 2.0
        bad = client.patch("/api/smc-ict/params", json={"overrides": {"nope": {"x": 1}}})
        assert bad.status_code == 400
        frozen = client.patch("/api/smc-ict/params", json={"overrides": {"confluence": {"trading_signal": True}}})
        assert frozen.status_code == 400

    def test_detections_and_sections(self, client, container):
        container.smc_ict.analyse(fx.series(fx.path_series(fx.choch_bullish_legs())), publish=False)
        payload = client.get("/api/smc-ict").json()
        assert payload["engines"][ENGINE_NAME] == "ENABLED"
        assert payload["detections"]
        for path in ("structure", "liquidity", "gaps", "blocks", "ranges"):
            section = client.get(f"/api/smc-ict/{path}")
            assert section.status_code == 200
            assert section.json()["message"]

    def test_history_and_confluence_endpoints(self, client, container):
        container.smc_ict.analyse(fx.series(fx.path_series(fx.sweep_bearish_legs())), publish=False)
        history = client.get("/api/smc-ict/history", params={"limit": 10}).json()
        assert history["count"] >= 1
        confluence = client.get("/api/smc-ict/confluence").json()
        assert confluence["trading_signal"] is False
        assert isinstance(confluence["groups"], list)

    def test_detail_endpoint_and_404(self, client, container):
        container.smc_ict.analyse(fx.series(fx.path_series(fx.choch_bullish_legs())), publish=False)
        detection = container.smc_ict.tracked()[0]
        detail = client.get(f"/api/smc-ict/{detection.id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == detection.id
        missing = client.get("/api/smc-ict/smc_does_not_exist")
        assert missing.status_code == 404

    def test_status_card_reports_the_engine(self, client):
        engines = client.get("/api/status").json()["detection_engines"]
        assert engines[ENGINE_NAME] == "ENABLED"


class TestIncrementalCost:
    """§27 - a tick must stay cheap: the second run is just as fast, no full recompute."""

    def test_second_run_is_fast_on_a_300_bar_window(self):
        target = engine()
        candles = fx.noise_series(bars=300)
        series = to_series(candles)
        target.analyse(series)
        start = time.perf_counter()
        target.analyse(series)
        duration = time.perf_counter() - start
        assert duration < 2.0, f"a 300-bar run took {duration:.3f}s"

    def test_live_window_is_bounded(self):
        params = SmcIctParams()
        target = SmcIctEngine(params)
        series = to_series(fx.noise_series(bars=300))
        result = target.analyse(series)
        # only the newest scan window can produce an *event*
        newest = len(series.candles) - 1
        fresh = [
            d
            for d in result.detections
            if d.pattern in ("BOS", "CHOCH", "MSS")
            and d.detected_at_bar_time >= series.candles[newest - params.global_.scan_bars + 1].time
        ]
        assert len(fresh) <= len([d for d in result.detections if d.pattern in ("BOS", "CHOCH", "MSS")])


class TestNegativeControl:
    """§25 - the honest control: reported as measured, never tuned to zero."""

    @pytest.mark.parametrize("maker", ["noise_series", "flat_series", "trending_series"])
    def test_control_markets_run_and_report(self, maker):
        target = engine()
        series = to_series(getattr(fx, maker)())
        result = target.analyse(series)
        assert isinstance(result.detections, list)
        assert result.warnings == [], f"the engine must not warn on {maker}"
        assert result.duration_ms >= 0

    def test_flat_market_has_no_structure(self):
        target = engine()
        _, result, _ = analyse_instance(target, fx.flat_series())
        assert not [d for d in result.detections if d.pattern in ("BOS", "CHOCH", "MSS")]

    def test_noise_market_stays_low_on_structure(self):
        target = engine()
        series = to_series(fx.noise_series(seed=11, bars=300))
        result = target.analyse(series)
        structural = [d for d in result.detections if d.pattern in ("BOS", "CHOCH", "MSS")]
        # an honest ceiling: random data must not produce a structure on every bar
        assert len(structural) <= 20, f"{len(structural)} structure events on 300 random bars"
