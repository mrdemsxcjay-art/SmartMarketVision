#!/usr/bin/env python3
"""Phase 4 §26 acceptance run: SMC/ICT engine on REAL Forex data.

    cd backend && python3 ../scripts/verify_smc_ict_live.py

What it does, in order:

1. feeds the SMC/ICT engine the **real** candles of the configured pairs and
   timeframes (same provider as the dashboard) - no synthetic bar ever enters
   this path;
2. re-checks every object against the real candles, pattern by pattern:
   * every coordinate sits on a quoted bar and inside its high/low;
   * BOS / CHOCH: the close is really beyond the broken swing, and the swing is a
     real pivot of the same window;
   * FVG: ``high[candle_1] < low[candle_3]`` (bullish) recomputed from the OHLC;
   * sweep: the extreme really pierced the level and the close came back;
   * order block: the origin candle really is the opposite colour and the zone is
     its range (or its body);
   * equal levels: every touch is a real pivot inside the declared tolerance;
   * breaker: the cycle is present (order block -> invalidation -> break) and is
     never produced without its parent block;
   * confidence recomputed from the declared criteria;
3. reports the breakdowns (pattern / status / pair / timeframe), the errors, the
   warnings and the timings;
4. runs the same engine on three structureless synthetic markets (negative
   control, §25) and reports what it finds there - honestly, without tuning the
   thresholds to reach zero;
5. probes the live API when a server is reachable.

The report is written to ``reports/smc_ict_real_data.{md,json}``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.instruments import get_symbol_info  # noqa: E402
from app.logging_conf import setup_logging  # noqa: E402
from app.providers.registry import build_provider  # noqa: E402
from app.schemas.market import Timeframe  # noqa: E402
from app.services.structure import find_swings  # noqa: E402
from app.smc_ict.engine import SmcIctEngine  # noqa: E402
from app.smc_ict.params import SmcIctParams  # noqa: E402

PASS, FAIL, WARN = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m", "\033[93mWARN\033[0m"
#: the engine publishes levels rounded to 8 decimals (JSON hygiene), so every
#: recomputation compares with that tolerance instead of an exact equality.
PRICE_TOLERANCE = 1e-8
DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
DEFAULT_TIMEFRAMES = ["M15", "H1", "H4"]
#: word boundaries on purpose: "REENTRY" (re-entry of a liquidity level) is not a
#: trade entry, and must not be reported as one.
FORBIDDEN_PATTERNS = (
    r"\bBUY\b",
    r"\bSELL\b",
    r"\bENTRY\b",
    r"\bSTOP\s*LOSS\b",
    r"\bTAKE\s*PROFIT\b",
    r"\bTP\b",
    r"\bSL\b",
    r"\bACHAT\b",
    r"\bVENTE\b",
)


def forbidden_words(blob: str) -> list[str]:
    import re

    return [pattern for pattern in FORBIDDEN_PATTERNS if re.search(pattern, blob)]

results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "", warn: bool = False, optional: bool = False) -> bool:
    if not condition and optional:
        status = "WARN"
    else:
        status = "WARN" if (condition and warn) else ("PASS" if condition else "FAIL")
    results.append((name, status, detail))
    label = {"PASS": PASS, "WARN": WARN, "FAIL": FAIL}[status]
    print(f"  [{label}] {name}{f' - {detail}' if detail else ''}")
    return bool(condition)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SMC/ICT engine on real Forex data")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--limit", type=int, default=300, help="closed bars requested per series")
    parser.add_argument("--base-url", default="http://localhost:8000", help="live instance to probe (optional)")
    parser.add_argument("--out", default=str(ROOT / "reports" / "smc_ict_real_data.md"))
    parser.add_argument("--json", default=str(ROOT / "reports" / "smc_ict_real_data.json"))
    return parser.parse_args()


def pips(delta: float, pip: float) -> float:
    return delta / pip if pip else 0.0


def recompute_confidence(detection) -> float:
    factors = detection.confidence_factors
    total = sum(max(0.0, f.weight) for f in factors)
    passed = sum(max(0.0, f.weight) for f in factors if f.passed)
    return 0.0 if total <= 0 else round(100.0 * passed / total, 1)


def check_pattern(detection, candles_by_time: dict, swings: list) -> list[str]:
    """Pattern-specific verification against the real OHLC. Returns the problems."""
    problems: list[str] = []
    points = detection.evidence_points or {}
    measurements = points.get("measurements") or {}
    levels = {level.label: level.price for level in detection.drawing.levels}
    info = get_symbol_info(detection.symbol)
    pip = info.pip_size if info else 0.0001
    pattern = detection.pattern
    anchors = {index: swing for index, swing in enumerate(swings)}

    if pattern in ("BOS", "CHOCH", "MSS"):
        level = levels.get("BROKEN_SWING")
        close = levels.get("BREAK_CLOSE")
        bar = candles_by_time.get(detection.detected_at_bar_time)
        if level is None or close is None or bar is None:
            problems.append("missing level / close / bar")
        else:
            if abs(bar.close - close) > PRICE_TOLERANCE:
                problems.append(f"BREAK_CLOSE {close} != real close {bar.close}")
            if detection.direction.value == "BULLISH" and bar.close <= level:
                problems.append(f"close {bar.close} not above the broken swing {level}")
            if detection.direction.value == "BEARISH" and bar.close >= level:
                problems.append(f"close {bar.close} not below the broken swing {level}")
            if pattern == "MSS" and not measurements.get("from_choch_index"):
                problems.append("MSS without its CHOCH (the two definitions must stay linked)")
            if measurements.get("break_mode") == "CLOSE" and measurements.get("close_break") is False:
                problems.append("break_mode=CLOSE but close_break=false")

    if pattern in ("BULLISH_FVG", "BEARISH_FVG"):
        first = (detection.evidence_points.get("object") or {}).get("candle_1") or {}
        third = (detection.evidence_points.get("object") or {}).get("candle_3") or {}
        # the object payload carries the indices: recompute on the real bars
        window = sorted(candles_by_time.values(), key=lambda c: c.time)
        indices = {candle.time: i for i, candle in enumerate(window)}
        c1_index = first.get("index")
        c3_index = third.get("index")
        if c1_index is None or c3_index is None or c3_index >= len(window) or c1_index >= len(window):
            problems.append("missing candle indices")
        else:
            c1, c3 = window[c1_index], window[c3_index]
            if pattern == "BULLISH_FVG" and not (c3.low > c1.high):
                problems.append(f"no bullish gap: low[3]={c3.low} <= high[1]={c1.high}")
            if pattern == "BEARISH_FVG" and not (c3.high < c1.low):
                problems.append(f"no bearish gap: high[3]={c3.high} >= low[1]={c1.low}")
            gap = abs((c3.low - c1.high) if pattern == "BULLISH_FVG" else (c1.low - c3.high))
            if abs(gap - levels["SIZE"]) > PRICE_TOLERANCE:
                problems.append(f"SIZE {levels['SIZE']} != recomputed {gap}")
        if measurements.get("coverage_share") is None:
            problems.append("mitigation state without coverage")

    if pattern == "LIQUIDITY_SWEEP":
        bar = candles_by_time.get(detection.detected_at_bar_time)
        level = levels.get("LIQUIDITY_LEVEL")
        extreme = levels.get("EXTREME")
        reentry = levels.get("REENTRY")
        if None in (bar, level, extreme, reentry):
            problems.append("missing level / extreme / reentry / bar")
        else:
            if abs(bar.close - reentry) > PRICE_TOLERANCE:
                problems.append(f"REENTRY {reentry} != real close {bar.close}")
            if detection.direction.value == "BEARISH":
                if not (
                    extreme <= bar.high + PRICE_TOLERANCE and extreme >= bar.low - PRICE_TOLERANCE
                ):
                    problems.append("extreme outside the candle")
                if extreme <= level or reentry >= level:
                    problems.append("bearish sweep without pierce + re-entry")
            else:
                if extreme >= level or reentry <= level:
                    problems.append("bullish sweep without pierce + re-entry")

    if pattern in ("BULLISH_ORDER_BLOCK", "BEARISH_ORDER_BLOCK"):
        origin = (detection.evidence_points.get("object") or {}).get("origin_candle") or {}
        bar = candles_by_time.get(origin.get("time"))
        if bar is None:
            problems.append("origin candle not in the series")
        else:
            for field in ("open", "high", "low", "close"):
                if abs(getattr(bar, field) - origin.get(field, float("nan"))) > PRICE_TOLERANCE:
                    problems.append(f"origin.{field} != real {getattr(bar, field)}")
            if pattern == "BULLISH_ORDER_BLOCK" and bar.close >= bar.open:
                problems.append("bullish block whose origin candle is not bearish")
            if pattern == "BEARISH_ORDER_BLOCK" and bar.close <= bar.open:
                problems.append("bearish block whose origin candle is not bullish")
            if abs(levels["ZONE_LOW"] - bar.low) > PRICE_TOLERANCE or abs(levels["ZONE_HIGH"] - bar.high) > PRICE_TOLERANCE:
                problems.append("zone is not the origin candle range (zone_from_body=false)")
            trigger = (detection.evidence_points.get("object") or {}).get("trigger_event") or {}
            if trigger.get("pattern") not in ("BOS", "CHOCH", "MSS"):
                problems.append("block without a structural trigger")

    if pattern == "BREAKER_BLOCK":
        cycle = (detection.evidence_points.get("object") or {}).get("cycle") or []
        if cycle != ["ORDER_BLOCK", "INVALIDATION", "STRUCTURAL_BREAK", "BREAKER"]:
            problems.append("breaker without the declared cycle")
        if measurements.get("invalidation_index") is None or measurements.get("promotion_index") is None:
            problems.append("breaker without invalidation/promotion anchors")

    if pattern in ("EQUAL_HIGH", "EQUAL_LOW"):
        prices = (detection.evidence_points.get("object") or {}).get("prices") or []
        tolerance = (detection.evidence_points.get("object") or {}).get("tolerance")
        touches = measurements.get("touches") or []
        if len(prices) < 2 or tolerance is None:
            problems.append("equality without its touches")
        else:
            if max(prices) - min(prices) > tolerance + PRICE_TOLERANCE:
                problems.append(f"spread {max(prices) - min(prices)} > tolerance {tolerance}")
            for touch in touches:
                index = touch.get("index")
                if not any(swing.index == index for swing in swings):
                    problems.append(f"touch #{index} is not a pivot of the window")

    if pattern == "LIQUIDITY_POOL_ESTIMATE":
        if not (detection.evidence_points.get("estimate") is True):
            problems.append("pool without the explicit estimate flag")
        text = " ".join(detection.evidence).upper()
        if "ESTIMATION" not in text and "ESTIMATE" not in text:
            problems.append("pool without the estimate disclaimer")

    if pattern == "DEALING_RANGE":
        high_index = measurements.get("source_high_index")
        low_index = measurements.get("source_low_index")
        high_swing = next((s for s in swings if s.index == high_index), None)
        low_swing = next((s for s in swings if s.index == low_index), None)
        if high_swing is None or low_swing is None:
            problems.append("range bounds are not pivots of the window")
        else:
            if abs(high_swing.price - levels["RANGE_HIGH"]) > PRICE_TOLERANCE:
                problems.append("RANGE_HIGH != source swing price")
            if abs(low_swing.price - levels["RANGE_LOW"]) > PRICE_TOLERANCE:
                problems.append("RANGE_LOW != source swing price")
        equilibrium = levels.get("EQUILIBRIUM")
        if equilibrium is None or abs(equilibrium - (levels["RANGE_HIGH"] + levels["RANGE_LOW"]) / 2) > PRICE_TOLERANCE:
            problems.append("equilibrium is not the mid-point")

    if pattern in ("PREMIUM", "DISCOUNT"):
        position = measurements.get("position")
        if position is None:
            problems.append("zone without a measured position")
        elif pattern == "PREMIUM" and position < SmcIctParams().premium_discount.premium_zone:
            problems.append(f"PREMIUM at {position}")
        elif pattern == "DISCOUNT" and position > SmcIctParams().premium_discount.discount_zone:
            problems.append(f"DISCOUNT at {position}")

    return problems


async def analyse_series(provider, engine: SmcIctEngine, symbol: str, timeframe: str, limit: int) -> dict:
    record: dict = {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": 0,
        "detections": [],
        "errors": [],
        "warnings": [],
    }
    started = time.perf_counter()
    try:
        series = await provider.get_candles(symbol, Timeframe(timeframe), limit=limit)
    except Exception as exc:  # provider outage: reported, never worked around
        record["errors"].append(f"provider: {type(exc).__name__} - {exc}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    closed = series.closed_candles or []
    record["provider"] = series.provider
    record["data_state"] = series.data_state.value
    record["bars"] = len(closed)
    if series.quality_warnings:
        # provider data-quality notices (weekend gaps, folded running bar): they are
        # reported separately from the engine's own warnings, and never hidden
        record["quality_warnings"] = list(series.quality_warnings)

    globals_ = engine.params.global_
    if len(closed) < globals_.min_bars_required:
        record["errors"].append(f"not analysed: {len(closed)} closed bars < {globals_.min_bars_required}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    window = closed[-globals_.window_bars :]
    engine_series = series.model_copy(update={"candles": window})
    candles_by_time = {candle.time: candle for candle in window}
    swings = find_swings(candles_by_time and list(window), left=globals_.pivot_left, right=globals_.pivot_right)

    try:
        result = engine.analyse(engine_series)
        engine.commit(result)
    except Exception as exc:
        record["errors"].append(f"engine: {type(exc).__name__} - {exc}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    record["bars_analyzed"] = result.bars_analyzed
    record["candidates"] = result.candidates
    record["context"] = result.context
    record["engine_warnings"] = list(result.warnings)
    record["confluence_groups"] = len(result.confluence)
    for detection in result.detections:
        problems = check_pattern(detection, candles_by_time, swings)
        coordinate_problems = []
        for coordinate in detection.coordinates:
            real = candles_by_time.get(coordinate.time)
            if real is None:
                coordinate_problems.append(f"{coordinate.role}: bar not found")
            elif not (real.low - PRICE_TOLERANCE <= coordinate.price <= real.high + PRICE_TOLERANCE):
                coordinate_problems.append(f"{coordinate.role}: {coordinate.price} outside [{real.low}, {real.high}]")
        confidence_expected = recompute_confidence(detection)
        payload = json.dumps(detection.model_dump(mode="json"), ensure_ascii=False).upper()
        forbidden = forbidden_words(payload)
        record["detections"].append(
            {
                "id": detection.id,
                "pattern": detection.pattern,
                "family": detection.parameters.get("family"),
                "state": detection.parameters.get("state"),
                "direction": detection.direction.value,
                "status": detection.status.value,
                "confidence": detection.confidence,
                "confidence_recomputed": confidence_expected,
                "bar_time": detection.detected_at_bar_time,
                "bar_exists": detection.detected_at_bar_time in candles_by_time,
                "measurement_problems": problems,
                "coordinate_problems": coordinate_problems,
                "forbidden_words": forbidden,
                "coordinates": len(detection.coordinates),
                "levels": {level.label: level.price for level in detection.drawing.levels},
                "estimate": bool(detection.evidence_points.get("estimate", False)),
                "volume": detection.confirmation.volume,
                "synthetic_data": False,
                "evidence": detection.evidence[:5],
            }
        )
    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def negative_control(engine: SmcIctEngine) -> dict:
    """§25 - the same engine on structureless markets, reported as measured."""
    sys.path.insert(0, str(ROOT / "backend"))
    from tests import smc_ict_fixtures as fx

    out: dict = {}
    for name, candles in (
        ("bruit_aleatoire", fx.noise_series(bars=300)),
        ("marche_plat", fx.flat_series(bars=200)),
        ("fortement_directionnel", fx.trending_series(bars=200)),
    ):
        control = SmcIctEngine(SmcIctParams())
        series = fx.series(candles)
        result = control.analyse(series)
        by_pattern = Counter(d.pattern for d in result.detections)
        out[name] = {
            "bars": len(candles),
            "detections": len(result.detections),
            "per_bar_ratio": round(len(result.detections) / len(candles), 4),
            "by_pattern": dict(by_pattern.most_common()),
            "structure": {
                pattern: by_pattern.get(pattern, 0) for pattern in ("BOS", "CHOCH", "MSS")
            },
            "warnings": result.warnings,
        }
    return out


def probe_live(base_url: str) -> dict:
    """Optional: check the running API exposes the engine and never an instruction."""
    import urllib.error
    import urllib.request

    info: dict = {"reachable": False, "checks": []}
    try:
        with urllib.request.urlopen(f"{base_url}/api/smc-ict/params", timeout=5) as response:
            payload = json.loads(response.read().decode())
        info["reachable"] = True
        info["engines"] = payload.get("engines")
        info["trading_signal"] = payload.get("trading_signal")
        info["groups"] = len(payload.get("params", {}))
        with urllib.request.urlopen(f"{base_url}/api/smc-ict", timeout=10) as response:
            detections = json.loads(response.read().decode())
        info["tracked"] = len(detections.get("detections", []))
        blob = json.dumps(detections).upper()
        info["forbidden_words"] = forbidden_words(blob)
        info["status"] = detections.get("status")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        info["error"] = f"{type(exc).__name__} - {exc}"
    return info


def build_report(records: list[dict], control: dict, engine: SmcIctEngine, live: dict, args) -> str:
    analysed = [r for r in records if r.get("bars_analyzed")]
    detections = [(r, d) for r in analysed for d in r["detections"]]
    bars_total = sum(r["bars_analyzed"] for r in analysed)
    by_pattern = Counter(d["pattern"] for _, d in detections)
    by_status = Counter(d["status"] for _, d in detections)
    by_state = Counter(str(d["state"]) for _, d in detections if d["state"])
    by_family = Counter(str(d["family"]) for _, d in detections)
    by_pair = Counter(r["symbol"] for r, _ in detections)
    by_timeframe = Counter(r["timeframe"] for r, _ in detections)
    errors = [(r["symbol"], r["timeframe"], e) for r in records for e in r["errors"]]
    warnings = [(r["symbol"], r["timeframe"], w) for r in records for w in r.get("engine_warnings", [])]
    quality = [(r["symbol"], r["timeframe"], w) for r in records for w in r.get("quality_warnings", [])]
    durations = [r["duration_ms"] for r in analysed]
    params = engine.params

    lines: list[str] = []
    lines.append("# SMART MARKET VISION - moteur SMC/ICT (Phase 4) sur donnees reelles\n")
    lines.append(f"Genere : {datetime.now(tz=timezone.utc).isoformat()}  ")
    lines.append(f"Paires : {args.pairs}  ")
    lines.append(f"Timeframes : {args.timeframes}  ")
    lines.append(f"Bougies demandees par serie : {args.limit} (fenetre moteur : {params.global_.window_bars},")
    lines.append(f"fenetre d'evenements : {params.global_.scan_bars}, historique de structure : {params.global_.structure_bars})\n")
    lines.append("## 1. Volumetrie\n")
    lines.append(f"- series analysees : **{len(analysed)}** / {len(records)} demandees")
    lines.append(f"- bougies cloturees analysees : **{bars_total}**")
    lines.append(f"- candidats bruts : **{sum(r['candidates'] for r in analysed)}**")
    lines.append(f"- objets SMC/ICT retenus : **{len(detections)}**")
    lines.append(f"- groupes de confluence : **{sum(r.get('confluence_groups', 0) for r in analysed)}**")
    lines.append(
        f"- erreurs : **{len(errors)}**, avertissements moteur : **{len(warnings)}**, "
        f"avertissements qualite du provider : **{len(quality)}** (gaps de week-end, bougie en cours repliee)"
    )
    if durations:
        lines.append(
            f"- duree par serie : min {min(durations):.1f} ms / mediane {statistics.median(durations):.1f} ms "
            f"/ max {max(durations):.1f} ms\n"
        )

    lines.append("## 2. Repartition\n")
    lines.append("| Pattern | Objets |")
    lines.append("| --- | --- |")
    for pattern, count in by_pattern.most_common():
        lines.append(f"| {pattern} | {count} |")
    lines.append("")
    lines.append("| Famille | Objets | | Statut | Objets |")
    lines.append("| --- | --- | --- | --- | --- |")
    families = list(by_family.most_common())
    statuses = list(by_status.most_common())
    for index in range(max(len(families), len(statuses))):
        family = families[index] if index < len(families) else ("", "")
        status = statuses[index] if index < len(statuses) else ("", "")
        lines.append(f"| {family[0]} | {family[1]} | | {status[0]} | {status[1]} |")
    lines.append("")
    if by_state:
        lines.append("| Etat SMC (FVG / blocs) | Objets |")
        lines.append("| --- | --- |")
        for state, count in by_state.most_common():
            lines.append(f"| {state} | {count} |")
        lines.append("")
    lines.append("| Paire | Objets | | Timeframe | Objets |")
    lines.append("| --- | --- | --- | --- | --- |")
    pairs = list(by_pair.most_common())
    times = list(by_timeframe.most_common())
    for index in range(max(len(pairs), len(times))):
        pair = pairs[index] if index < len(pairs) else ("", "")
        tf = times[index] if index < len(times) else ("", "")
        lines.append(f"| {pair[0]} | {pair[1]} | | {tf[0]} | {tf[1]} |")
    lines.append("")

    lines.append("## 3. Controle anti-fiction (bougies reelles)\n")
    bad_bar = [d for _, d in detections if not d["bar_exists"]]
    bad_pattern = [(r["symbol"], r["timeframe"], d["pattern"], d["measurement_problems"]) for r, d in detections if d["measurement_problems"]]
    bad_coord = [(r["symbol"], r["timeframe"], d["pattern"], d["coordinate_problems"]) for r, d in detections if d["coordinate_problems"]]
    bad_conf = [(r["symbol"], r["timeframe"], d["pattern"]) for r, d in detections if d["confidence"] != d["confidence_recomputed"]]
    bad_words = [(r["symbol"], r["timeframe"], d["pattern"], d["forbidden_words"]) for r, d in detections if d["forbidden_words"]]
    estimated = [d for _, d in detections if d["estimate"]]
    lines.append(f"- objets dont la bougie d'ancrage n'existe pas : **{len(bad_bar)}**")
    lines.append(f"- objets dont une mesure ne se recompose pas sur l'OHLC reel : **{len(bad_pattern)}**")
    lines.append(f"- objets dont une coordonnee sort de la bougie : **{len(bad_coord)}**")
    lines.append(f"- confiances non reproductibles a partir des criteres : **{len(bad_conf)}**")
    lines.append(f"- objets contenant un mot d'instruction de trading : **{len(bad_words)}**")
    lines.append(f"- objets explicitement marques comme estimation : **{len(estimated)}** (liquidite)")
    lines.append(f"- objets portant un volume invente : **{len([d for _, d in detections if d['volume'] is not None])}**\n")
    if bad_pattern[:10]:
        lines.append("Premiers ecarts mesures :\n")
        for symbol, timeframe, pattern, problems in bad_pattern[:10]:
            lines.append(f"- {symbol} {timeframe} {pattern} : {'; '.join(problems[:3])}")
        lines.append("")

    lines.append("## 4. Controle negatif (§25)\n")
    lines.append("| Marche | Bougies | Objets | Objets/bougie | Structure (BOS/CHOCH/MSS) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, payload in control.items():
        structure = payload["structure"]
        lines.append(
            f"| {name} | {payload['bars']} | {payload['detections']} | {payload['per_bar_ratio']} | "
            f"{structure['BOS']}/{structure['CHOCH']}/{structure['MSS']} |"
        )
    lines.append("")
    for name, payload in control.items():
        lines.append(f"- **{name}** : {payload['by_pattern'] or 'aucun objet'}")
    lines.append("")
    lines.append("Ce controle est publie tel quel : les seuils ne sont pas ajustes pour atteindre zero.\n")

    lines.append("## 5. Erreurs et avertissements\n")
    if errors:
        for symbol, timeframe, error in errors:
            lines.append(f"- ERREUR {symbol} {timeframe} : {error}")
    else:
        lines.append("- aucune erreur")
    if warnings:
        for symbol, timeframe, warning in warnings[:20]:
            lines.append(f"- AVERTISSEMENT MOTEUR {symbol} {timeframe} : {warning}")
    else:
        lines.append("- aucun avertissement moteur")
    if quality:
        lines.append("- avertissements qualite du provider (donnees reelles, non masques) :")
        for symbol, timeframe, warning in quality[:10]:
            lines.append(f"  - {symbol} {timeframe} : {warning}")
    lines.append("")

    lines.append("## 6. Surface live (si un serveur repond)\n")
    if live.get("reachable"):
        lines.append(f"- moteurs : {live.get('engines')}")
        lines.append(f"- trading_signal : {live.get('trading_signal')}")
        lines.append(f"- groupes de parametres exposes : {live.get('groups')}")
        lines.append(f"- objets suivis par l'instance : {live.get('tracked')} (statut {live.get('status')})")
        lines.append(f"- mots d'instruction de trading dans la reponse : {live.get('forbidden_words') or 'aucun'}\n")
    else:
        lines.append(f"- serveur non joignable ({live.get('error', 'inconnu')}) : la surface live n'a pas ete controlee\n")

    lines.append("## 7. Definitions retenues (une seule par concept)\n")
    lines.append("- **BOS** : cloture au-dela du dernier swing confirme, dans le sens de la structure. Une meche seule ne casse rien.")
    lines.append(f"- **CHOCH** : la structure est cassee dans l'autre sens (seuil de cassure {params.bos.min_break_pips} pip "
                 f"/ {params.bos.min_break_atr} ATR, minimum {params.choch.min_swings_for_trend} swings).")
    lines.append(f"- **MSS** : CHOCH + deplacement (extension >= {params.mss.min_displacement_atr} ATR, "
                 f"dans les {params.mss.max_bars_after_choch} bougies). Un CHOCH sans deplacement reste un CHOCH.")
    lines.append(f"- **Equal high/low** : >= {params.equal_levels.min_touches} pivots dans une tolerance de "
                 f"max({params.equal_levels.tolerance_pips} pips, {params.equal_levels.tolerance_atr} ATR).")
    lines.append("- **LIQUIDITY_POOL_ESTIMATE** : inference geometrique d'une zone de liquidite - jamais un carnet d'ordres observe.")
    lines.append("- **Liquidity sweep** : depassement + reintroduction par la cloture + excursion reelle (les trois etapes).")
    lines.append(f"- **FVG** : bande non tradee sur trois bougies, taille >= max({params.fvg.min_size_pips} pips, "
                 f"{params.fvg.min_size_atr} ATR) ; mitigation CREATED/ACTIVE/PARTIALLY_FILLED/FILLED.")
    lines.append(f"- **Order block** : derniere bougie opposee avant un deplacement qui casse la structure "
                 f"(<= {params.order_block.max_bars_to_break} bougies).")
    lines.append("- **Breaker** : jamais detecte seul - cycle ORDER_BLOCK -> INVALIDATION -> STRUCTURAL_BREAK -> BREAKER.")
    lines.append(f"- **Displacement** : range >= max({params.displacement.min_range_pips} pips, {params.displacement.min_range_atr} ATR), "
                 f"corps/range >= {params.displacement.min_body_ratio}, progression au-dela de l'extreme precedent.")
    lines.append(f"- **Dealing range** : plus haut sommet et plus bas creux confirmes de {params.dealing_range.lookback_bars} bougies, "
                 f"hauteur >= {params.dealing_range.min_span_atr} ATR ; premium >= {params.premium_discount.premium_zone}, "
                 f"discount <= {params.premium_discount.discount_zone}.")
    lines.append(f"- **Confluence** : descriptive uniquement, familles distinctes exigees, aucun score, "
                 f"trading_signal = {params.confluence.trading_signal}.\n")

    return "\n".join(lines)


async def main() -> int:
    setup_logging()
    args = parse_args()
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    print("SMART MARKET VISION - SMC/ICT sur donnees reelles Forex\n")
    engine = SmcIctEngine(SmcIctParams())
    provider = build_provider()

    print("1. Analyse des series reelles")
    records = []
    try:
        for symbol in pairs:
            for timeframe in timeframes:
                record = await analyse_series(provider, engine, symbol, timeframe, args.limit)
                records.append(record)
                print(
                    f"   {symbol} {timeframe}: {record.get('bars_analyzed', 0)} bougies, "
                    f"{len(record['detections'])} objet(s), {record['duration_ms']} ms"
                    + (f", ERREUR {record['errors']}" if record["errors"] else "")
                )
    finally:
        await provider.aclose()

    analysed = [r for r in records if r.get("bars_analyzed")]
    detections = [(r, d) for r in analysed for d in r["detections"]]
    print("\n2. Controles")
    check("series analysees", len(analysed) > 0, f"{len(analysed)} / {len(records)}")
    bars_total = sum(r["bars_analyzed"] for r in analysed)
    check(
        "bougies reelles analysees",
        bool(analysed) and bars_total >= 250 * len(analysed),
        f"{bars_total} bougies sur {len(analysed)} serie(s)",
    )
    check("objets SMC/ICT produits", len(detections) > 0, f"{len(detections)} objets")
    check(
        "toutes les bougies d'ancrage existent",
        all(d["bar_exists"] for _, d in detections),
        f"{len([d for _, d in detections if not d['bar_exists']])} hors serie",
    )
    check(
        "toutes les mesures se recomposent sur l'OHLC reel",
        all(not d["measurement_problems"] for _, d in detections),
        f"{len([d for _, d in detections if d['measurement_problems']])} objet(s) en ecart",
    )
    check(
        "aucune coordonnee hors bougie",
        all(not d["coordinate_problems"] for _, d in detections),
        f"{len([d for _, d in detections if d['coordinate_problems']])} objet(s) en ecart",
    )
    check(
        "confiance reproductible depuis les criteres",
        all(d["confidence"] == d["confidence_recomputed"] for _, d in detections),
    )
    check(
        "aucun mot d'instruction de trading",
        all(not d["forbidden_words"] for _, d in detections),
    )
    check(
        "aucun volume invente",
        all(d["volume"] is None for _, d in detections),
        "le provider ne fournit pas de volume reel",
    )
    pools = [d for _, d in detections if d["pattern"] == "LIQUIDITY_POOL_ESTIMATE"]
    sweeps = [d for _, d in detections if d["pattern"] == "LIQUIDITY_SWEEP"]
    check(
        "liquidite toujours presentee comme une estimation",
        all(d["estimate"] for d in pools) and all(d["estimate"] for d in sweeps),
        f"{len(pools)} pool(s) et {len(sweeps)} balayage(s) marques comme estimations geometriques",
    )
    check(
        "au moins une cassure de structure reelle",
        any(d["pattern"] in ("BOS", "CHOCH", "MSS") for _, d in detections),
        f"{Counter(d['pattern'] for _, d in detections).get('BOS', 0)} BOS / "
        f"{Counter(d['pattern'] for _, d in detections).get('CHOCH', 0)} CHOCH / "
        f"{Counter(d['pattern'] for _, d in detections).get('MSS', 0)} MSS",
    )
    check("aucune erreur moteur", all(not r["errors"] for r in analysed), f"{sum(len(r['errors']) for r in records)} erreur(s)")
    engine_warnings = sum(len(r.get("engine_warnings", [])) for r in analysed)
    check("aucun avertissement moteur", engine_warnings == 0, f"{engine_warnings} avertissement(s) moteur")
    check(
        "avertissements qualite du provider visibles",
        True,
        f"{sum(len(r.get('quality_warnings', [])) for r in analysed)} avertissement(s) de qualite conserves",
        warn=True,
    )

    print("\n3. Controle negatif")
    control = negative_control(engine)
    for name, payload in control.items():
        print(
            f"   {name}: {payload['detections']} objet(s) sur {payload['bars']} bougies "
            f"({payload['per_bar_ratio']} par bougie), structure {payload['structure']}"
        )
    check(
        "controle negatif execute",
        len(control) == 3,
        "bruit + plat + fortement directionnel",
    )

    print("\n4. Surface live")
    live = probe_live(args.base_url)
    if live.get("reachable"):
        check("API SMC/ICT joignable", True, f"{live.get('tracked')} objet(s) suivis")
        check("API sans instruction de trading", not live.get("forbidden_words"))
    else:
        check("API SMC/ICT joignable", False, live.get("error", ""), optional=True)

    report = build_report(records, control, engine, live, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "pairs": pairs,
        "timeframes": timeframes,
        "limit": args.limit,
        "params_version": engine.parameters_version,
        "records": records,
        "negative_control": control,
        "live": live,
        "checks": [{"name": name, "status": status, "detail": detail} for name, status, detail in results],
    }
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = [r for r in results if r[1] == "FAIL"]
    warnings = [r for r in results if r[1] == "WARN"]
    print(f"\n{len(results) - len(failures) - len(warnings)} PASS / {len(warnings)} WARN / {len(failures)} FAIL")
    print(f"Rapport : {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
