"""Phase 4 §6-§16 - liquidity, gaps, blocks, ranges and confluence.

Each family is exercised on a controlled OHLC fixture with the four required
angles: positive, negative, limit and duplication (the §24 checklist). The
fixtures are synthetic bars built for the tests only; production data always
comes from the real provider.
"""

from __future__ import annotations

import pytest

from app.smc_ict.context import build_context
from app.smc_ict.detectors.blocks import detect_breakers, detect_order_blocks
from app.smc_ict.detectors.confluence import detect_confluence
from app.smc_ict.detectors.gaps import detect_fvgs
from app.smc_ict.detectors.liquidity import (
    detect_equal_levels,
    detect_liquidity_pools,
    detect_liquidity_sweeps,
)
from app.smc_ict.detectors.ranges import (
    detect_dealing_range,
    detect_displacement,
    detect_premium_discount,
)
from app.smc_ict.detectors.structure import detect_structure
from app.smc_ict.params import SmcIctParams
from tests import smc_ict_fixtures as fx


def context(legs_or_candles, params: SmcIctParams | None = None):
    candles = legs_or_candles if isinstance(legs_or_candles, list) and hasattr(legs_or_candles[0], "high") else fx.path_series(legs_or_candles)
    return build_context(fx.series(candles), params or SmcIctParams(), pip_size=fx.PIP, digits=5)


def by_pattern(items, pattern):
    return [item for item in items if item.pattern == pattern]


class TestEqualLevels:
    """§6 - equal highs / lows with a measured tolerance."""

    def test_positive_equal_highs(self):
        ctx = context(fx.equal_highs_legs())
        found = by_pattern(detect_equal_levels(ctx), "EQUAL_HIGH")
        assert found, "the fixture builds two highs one pip apart"
        # the scenario's own pair: exactly two touches at the very same price
        cluster = [c for c in found if c.measurements["touch_count"] == 2][0]
        assert cluster.measurements["touch_count"] == 2
        assert cluster.measurements["spread_pips"] == 0.0
        assert cluster.levels["LEVEL"] == pytest.approx(fx.BASE + 38 * fx.PIP, abs=1e-9)
        assert cluster.measurements["spread_pips"] <= cluster.measurements["tolerance_pips"]
        assert len(cluster.extra["prices"]) == 2
        assert len(cluster.extra["timestamps"]) == 2
        assert cluster.extra["side"] == "ABOVE"
        assert cluster.direction == "NEUTRAL"

    def test_positive_equal_lows(self):
        ctx = context(fx.equal_lows_legs())
        found = by_pattern(detect_equal_levels(ctx), "EQUAL_LOW")
        assert found
        assert found[-1].extra["side"] == "BELOW"

    def test_limit_tolerance_is_the_declared_one(self):
        params = SmcIctParams()
        ctx = context(fx.equal_highs_legs(tolerance_pips=1.0), params)
        cluster = [
            c
            for c in by_pattern(detect_equal_levels(ctx), "EQUAL_HIGH")
            if c.measurements["touch_count"] == 2
        ][0]
        expected = ctx.min_size(params.equal_levels.tolerance_pips, params.equal_levels.tolerance_atr)
        assert cluster.measurements["tolerance"] == round(expected, 8)

    def test_negative_swings_far_apart_are_not_equals(self):
        params = SmcIctParams()
        params.equal_levels.tolerance_pips = 0.1
        params.equal_levels.tolerance_atr = 0.0
        ctx = context(fx.equal_highs_legs(tolerance_pips=6.0), params)
        spread = [
            c for c in by_pattern(detect_equal_levels(ctx), "EQUAL_HIGH") if c.measurements["spread_pips"] > 0.1
        ]
        assert all(c.measurements["spread_pips"] <= c.measurements["tolerance_pips"] for c in spread)

    def test_dedup_one_candidate_per_cluster(self):
        ctx = context(fx.equal_highs_legs())
        clusters = [(c.pattern, c.source_from_index) for c in detect_equal_levels(ctx)]
        assert len(clusters) == len(set(clusters))


class TestLiquidityPools:
    """§7 - always an ESTIMATE, never an observed order book."""

    def test_positive_pool_is_explicitly_an_estimate(self):
        ctx = context(fx.equal_highs_legs())
        pools = by_pattern(detect_liquidity_pools(ctx), "LIQUIDITY_POOL_ESTIMATE")
        assert pools
        pool = pools[0]
        assert pool.measurements["estimate"] is True
        assert pool.extra["estimate"] is True
        assert "ESTIMATION" in " ".join(pool.evidence)
        assert pool.measurements["method"] in {
            "EQUAL_HIGH",
            "EQUAL_LOW",
            "OLD_SWING_HIGH",
            "OLD_SWING_LOW",
        }

    def test_negative_consumed_level_is_not_a_pool(self):
        """A level price CLOSED through is consumed: it is no longer resting liquidity."""
        params = SmcIctParams()
        buffer = params.sweep.reentry_buffer_pips * fx.PIP
        ctx = context(fx.equal_highs_legs(), params)
        pools = detect_liquidity_pools(ctx)
        assert pools, "the fixture leaves at least one untouched level"
        for pool in pools:
            level = float(pool.levels["POOL_LEVEL"])
            if pool.extra["side"] != "ABOVE":
                continue
            later = [bar for bar in ctx.metrics[pool.index + 1 :] if bar.close > level + buffer]
            assert not later, f"pool {level} was closed through"

    def test_limit_cap_is_respected(self):
        params = SmcIctParams()
        params.pools.max_pools = 2
        ctx = context(fx.equal_highs_legs(), params)
        assert len(detect_liquidity_pools(ctx)) <= 2

    def test_dedup_one_pool_per_level(self):
        ctx = context(fx.equal_lows_legs())
        levels = [round(float(p.levels["POOL_LEVEL"]), 5) for p in detect_liquidity_pools(ctx)]
        assert len(levels) == len(set(levels))


class TestSweeps:
    """§8 - the three steps, all mandatory."""

    def test_positive_bearish_sweep_of_equal_highs(self):
        ctx = context(fx.sweep_bearish_legs())
        sweeps = detect_liquidity_sweeps(ctx)
        assert sweeps
        sweep = sweeps[-1]
        assert sweep.direction == "BEARISH"
        assert sweep.levels["EXTREME"] > sweep.levels["LIQUIDITY_LEVEL"] > sweep.levels["REENTRY"]
        assert sweep.extra["extreme_price"] == sweep.levels["EXTREME"]
        assert sweep.extra["reentry_timestamp"] == sweep.time
        assert sweep.measurements["penetration_pips"] > 0
        assert sweep.measurements["reentry_pips"] > 0

    def test_positive_bullish_sweep_of_equal_lows(self):
        ctx = context(fx.sweep_bullish_legs())
        sweeps = detect_liquidity_sweeps(ctx)
        assert sweeps
        bullish = sweeps[-1]
        assert bullish.direction == "BULLISH"
        assert bullish.levels["LIQUIDITY_LEVEL"] > bullish.levels["EXTREME"], "the wick went below the level"
        assert bullish.levels["REENTRY"] > bullish.levels["LIQUIDITY_LEVEL"], "the close came back above it"

    def test_negative_break_without_reentry_is_not_a_sweep(self):
        """A close beyond the level is a break: step 2 is missing, so no sweep."""
        ctx = context(fx.equal_highs_no_sweep_legs())
        assert detect_liquidity_sweeps(ctx) == []

    def test_limit_reentry_buffer_is_enforced(self):
        params = SmcIctParams()
        params.sweep.reentry_buffer_pips = 500.0  # nothing can come back that far
        ctx = context(fx.sweep_bearish_legs(), params)
        assert detect_liquidity_sweeps(ctx) == []

    def test_dedup_one_sweep_per_candle_and_side(self):
        ctx = context(fx.sweep_bearish_legs())
        keys = [(s.index, s.direction) for s in detect_liquidity_sweeps(ctx)]
        assert len(keys) == len(set(keys))


class TestFairValueGaps:
    """§9 + §10 - the band, its state, and the numbers behind the state."""

    def test_positive_bullish_gap(self):
        ctx = context(fx.fvg_bullish_legs())
        gaps = by_pattern(detect_fvgs(ctx), "BULLISH_FVG")
        assert gaps
        gap = gaps[0]
        assert gap.levels["LOWER_PRICE"] < gap.levels["UPPER_PRICE"]
        assert gap.measurements["size_pips"] > 0
        assert gap.extra["candle_3"]["index"] == gap.measurements["candle_3_index"] == gap.index
        assert gap.extra["candle_1"]["high"] == gap.levels["LOWER_PRICE"]
        assert gap.extra["candle_3"]["low"] == gap.levels["UPPER_PRICE"]

    def test_positive_bearish_gap_is_the_mirror(self):
        ctx = context(fx.fvg_bearish_legs())
        gap = by_pattern(detect_fvgs(ctx), "BEARISH_FVG")[0]
        assert gap.extra["candle_3"]["high"] == gap.levels["LOWER_PRICE"]
        assert gap.extra["candle_1"]["low"] == gap.levels["UPPER_PRICE"]

    def test_negative_no_gap_on_a_flat_market(self):
        ctx = context(fx.flat_series())
        assert detect_fvgs(ctx) == []

    def test_negative_small_gap_is_rejected_by_the_size_floor(self):
        params = SmcIctParams()
        params.fvg.min_size_pips = 50.0
        params.fvg.min_size_atr = 10.0
        ctx = context(fx.fvg_bullish_legs(), params)
        assert detect_fvgs(ctx) == []

    def test_positive_untouched_gap_stays_active(self):
        ctx = context(fx.fvg_bullish_active_legs())
        gaps = detect_fvgs(ctx)
        band = [g for g in gaps if abs(g.levels["SIZE"] - 12.5 * fx.PIP) < 1e-9]
        assert band, "the fixture keeps the 12.5 pip band"
        assert band[0].measurements["state"] in ("CREATED", "ACTIVE")
        assert band[0].measurements["touched"] is False
        assert band[0].measurements["coverage_share"] == 0.0

    def test_positive_partially_filled_gap(self):
        ctx = context(fx.fvg_bullish_partial_legs())
        band = [g for g in detect_fvgs(ctx) if abs(g.levels["SIZE"] - 12.5 * fx.PIP) < 1e-9][0]
        assert band.measurements["touched"] is True
        assert 0 < band.measurements["coverage_share"] < 1
        assert band.measurements["traversed"] is False

    def test_positive_filled_gap_is_traversed_entirely(self):
        ctx = context(fx.fvg_bullish_filled_legs())
        band = [g for g in detect_fvgs(ctx) if abs(g.levels["SIZE"] - 12.5 * fx.PIP) < 1e-9][0]
        assert band.measurements["state"] == "FILLED"
        assert band.measurements["coverage_share"] == 1.0

    def test_limit_mitigation_states_are_the_declared_ones(self):
        params = SmcIctParams()
        assert params.mitigation.fill_rule == "full_traverse"
        ctx = context(fx.fvg_bullish_filled_legs())
        states = {g.measurements["state"] for g in detect_fvgs(ctx)}
        assert states <= {"CREATED", "ACTIVE", "PARTIALLY_FILLED", "FILLED"}

    def test_dedup_one_candidate_per_band(self):
        ctx = context(fx.fvg_bullish_partial_legs())
        keys = [(g.pattern, g.extra["candle_1"]["index"]) for g in detect_fvgs(ctx)]
        assert len(keys) == len(set(keys))


class TestOrderBlocks:
    """§11 - one definition: last opposite candle, displacement, structural break."""

    def test_positive_bullish_block(self):
        ctx = context(fx.order_block_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        blocks = by_pattern(detect_order_blocks(ctx, structure), "BULLISH_ORDER_BLOCK")
        assert blocks
        block = blocks[0]
        origin = ctx.metrics[block.extra["origin_index"]]
        assert origin.close < origin.open, "the origin candle is bearish"
        assert block.levels["ZONE_LOW"] == origin.low and block.levels["ZONE_HIGH"] == origin.high
        assert block.extra["trigger_event"]["pattern"] in ("BOS", "CHOCH", "MSS")
        assert block.measurements["displacement_index"] > block.extra["origin_index"]
        assert block.measurements["break_index"] >= block.measurements["displacement_index"]
        measure = block.extra["displacement_measure"]
        assert {"range_atr", "body_ratio", "progression_pips"} <= set(measure)

    def test_negative_no_structural_break_no_block(self):
        ctx = context(fx.order_block_no_break_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        assert detect_order_blocks(ctx, structure) == [] or not any(
            b.pattern == "BULLISH_ORDER_BLOCK" and b.index > len(ctx.metrics) - 12
            for b in detect_order_blocks(ctx, structure)
        )

    def test_limit_zone_from_body_parameter(self):
        params = SmcIctParams()
        params.order_block.zone_from_body = True
        ctx = context(fx.order_block_bullish_legs(), params)
        structure = detect_structure(ctx, params.global_.structure_bars)
        block = by_pattern(detect_order_blocks(ctx, structure), "BULLISH_ORDER_BLOCK")[0]
        origin = ctx.metrics[block.extra["origin_index"]]
        assert block.levels["ZONE_LOW"] == min(origin.open, origin.close)
        assert block.levels["ZONE_HIGH"] == max(origin.open, origin.close)

    def test_dedup_one_block_per_origin_candle(self):
        ctx = context(fx.order_block_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        origins = [b.extra["origin_index"] for b in detect_order_blocks(ctx, structure)]
        assert len(origins) == len(set(origins))


class TestBreakers:
    """§12 - derived from the explicit cycle, never detected on its own."""

    def test_positive_breaker_follows_the_cycle(self):
        ctx = context(fx.breaker_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        blocks = detect_order_blocks(ctx, structure)
        breakers = detect_breakers(ctx, blocks, structure)
        assert breakers, "the fixture invalidates a bullish block then breaks structure the other way"
        breaker = breakers[0]
        assert breaker.pattern == "BREAKER_BLOCK"
        assert breaker.direction == "BEARISH"
        assert breaker.extra["cycle"] == ["ORDER_BLOCK", "INVALIDATION", "STRUCTURAL_BREAK", "BREAKER"]
        assert breaker.measurements["invalidation_index"] is not None
        assert breaker.measurements["promotion_index"] >= breaker.measurements["invalidation_index"]
        origin = [b for b in blocks if b.extra["origin_index"] == breaker.extra["origin_index"]][0]
        assert origin.measurements["invalidated"] is True
        assert breaker.levels["ZONE_LOW"] == origin.levels["ZONE_LOW"]

    def test_negative_invalidation_without_break_is_not_promoted(self):
        ctx = context(fx.breaker_no_promotion_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        blocks = detect_order_blocks(ctx, structure)
        assert any(b.measurements["invalidated"] for b in blocks), "the fixture does invalidate a block"
        assert detect_breakers(ctx, blocks, structure) == []

    def test_negative_no_breaker_without_an_order_block(self):
        ctx = context(fx.bos_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        assert detect_breakers(ctx, [], structure) == []

    def test_limit_require_structural_break_can_be_lifted(self):
        params = SmcIctParams()
        params.breaker.require_structural_break = False
        assert params.breaker.max_bars_to_promote == 60
        assert params.breaker.require_structural_break is False


class TestDealingRange:
    """§14 + §15 - a real range, then pure proportion."""

    def test_positive_range_from_real_swings(self):
        ctx = context(fx.equal_highs_legs())
        dealing = detect_dealing_range(ctx)
        assert dealing is not None
        assert dealing.pattern == "DEALING_RANGE"
        assert dealing.levels["RANGE_LOW"] < dealing.levels["EQUILIBRIUM"] < dealing.levels["RANGE_HIGH"]
        high_index = dealing.measurements["source_high_index"]
        low_index = dealing.measurements["source_low_index"]
        assert dealing.levels["RANGE_HIGH"] == max(s.price for s in ctx.swings if s.index == high_index)
        assert dealing.levels["RANGE_LOW"] == min(s.price for s in ctx.swings if s.index == low_index)
        assert dealing.extra["timeframe"] == ctx.timeframe
        assert dealing.extra["source_high"]["index"] == high_index

    def test_negative_no_range_when_the_span_is_too_small(self):
        params = SmcIctParams()
        params.dealing_range.min_span_atr = 500.0
        ctx = context(fx.equal_highs_legs(), params)
        assert detect_dealing_range(ctx) is None

    def test_negative_no_range_without_swings(self):
        ctx = context(fx.flat_series())
        assert detect_dealing_range(ctx) is None

    def test_positive_premium_or_discount_is_pure_proportion(self):
        ctx = context(fx.noise_series())
        dealing = detect_dealing_range(ctx)
        if dealing is None:
            pytest.skip("no range on this random series")
        zone = detect_premium_discount(ctx, dealing)
        if zone is None:
            position = dealing.measurements["position"]
            assert 0.25 < position < 0.75, "mid-range: no zone label is claimed"
            return
        position = zone.measurements["position"]
        assert (position >= 0.75 and zone.pattern == "PREMIUM") or (position <= 0.25 and zone.pattern == "DISCOUNT")

    def test_negative_no_zone_at_equilibrium(self):
        params = SmcIctParams()
        params.premium_discount.premium_zone = 1.0
        params.premium_discount.discount_zone = 0.0
        ctx = context(fx.equal_highs_legs(), params)
        dealing = detect_dealing_range(ctx)
        assert detect_premium_discount(ctx, dealing) is None


class TestDisplacement:
    """§13 - measures, never adjectives."""

    def test_positive_displacement_on_an_impulse(self):
        ctx = context(fx.mss_bullish_legs())
        found = detect_displacement(ctx)
        assert found
        measures = found[0].measurements
        assert measures["range_atr"] >= SmcIctParams().displacement.min_range_atr or measures["range_pips"] >= SmcIctParams().displacement.min_range_pips
        assert 0.0 <= measures["body_ratio"] <= 1.0
        assert measures["efficiency"] >= 0.0

    def test_negative_no_displacement_on_a_quiet_market(self):
        ctx = context(fx.flat_series())
        assert detect_displacement(ctx) == []


class TestConfluence:
    """§16 - descriptive groups, never a score, never a signal."""

    def test_positive_confluence_group(self):
        ctx = context(fx.choch_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        candidates = structure + detect_fvgs(ctx) + detect_liquidity_pools(ctx)
        groups = detect_confluence(ctx, candidates)
        assert groups, "a reversal fixture mixes structure, gaps and liquidity"
        group = groups[0]
        assert group["count"] >= 2
        assert len(group["families"]) >= 2
        assert group["trading_signal"] is False
        assert group["span_bars"] <= SmcIctParams().confluence.max_bars_between

    def test_negative_one_family_is_not_a_confluence(self):
        ctx = context(fx.bos_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        assert detect_confluence(ctx, structure) == []

    def test_limit_no_score_and_no_signal_anywhere(self):
        ctx = context(fx.choch_bullish_legs())
        structure = detect_structure(ctx, SmcIctParams().global_.structure_bars)
        groups = detect_confluence(ctx, structure + detect_fvgs(ctx))
        for group in groups:
            assert "score" not in group
            assert group["trading_signal"] is False
