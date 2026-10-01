#!/usr/bin/env python3
"""Phase 3 acceptance run: price-action engine on REAL Forex data.

    cd backend && python3 ../scripts/verify_price_action_live.py

What it does, in order:

1. feeds the price-action engine the **real** candles of the configured pairs and
   timeframes (same provider as the dashboard) - no synthetic bar ever enters
   this path, and the chartist engine runs first so the price-action engine gets
   the real levels and the confirmed breakouts;
2. re-checks every detection against the real candles: bar time exists,
   coordinates inside the quoted candle, body/wick measurements recomputed from
   the OHLC, confidence recomputed from the declared criteria;
3. reports the breakdowns (pattern / pair / timeframe / status), the errors, the
   warnings and the timings;
4. runs the same engine on a synthetic structureless series (negative control)
   and reports how many patterns it invents there - honestly, without tuning the
   rules to reach zero;
5. if a server is reachable, checks the live API surface (engines, safety flags,
   no trading instruction anywhere).

The report is written to ``reports/price_action_real_data.{md,json}``.
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

from app.logging_conf import setup_logging  # noqa: E402
from app.instruments import get_symbol_info  # noqa: E402
from app.patterns.engine import ChartPatternEngine  # noqa: E402
from app.patterns.params import PatternParams  # noqa: E402
from app.price_action.engine import STATE_PATTERNS, PriceActionEngine  # noqa: E402
from app.price_action.params import PriceActionParams  # noqa: E402
from app.providers.registry import build_provider  # noqa: E402
from app.schemas.market import Candle, CandleSeries, DataState, Timeframe  # noqa: E402

PASS, FAIL, WARN = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m", "\033[93mWARN\033[0m"
DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
DEFAULT_TIMEFRAMES = ["M15", "H1", "H4"]
# §22: only DETECTED / CONFIRMED / INVALIDATED / EXPIRED and objective structure
# facts may be exposed - never a trade instruction.
FORBIDDEN = ("BUY", "SELL", "ENTRY", "STOP LOSS", "TAKE PROFIT", " TP ", " SL ", "ACHAT", "VENTE")

results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "", warn: bool = False) -> bool:
    status = "WARN" if (condition and warn) else ("PASS" if condition else "FAIL")
    results.append((name, status, detail))
    label = {"PASS": PASS, "WARN": WARN, "FAIL": FAIL}[status]
    print(f"  [{label}] {name}{f' - {detail}' if detail else ''}")
    return bool(condition)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Price-action engine on real Forex data")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--limit", type=int, default=300, help="closed bars requested per series")
    parser.add_argument("--base-url", default="http://localhost:8000", help="live instance to probe (optional)")
    parser.add_argument("--out", default=str(ROOT / "reports" / "price_action_real_data.md"))
    parser.add_argument("--json", default=str(ROOT / "reports" / "price_action_real_data.json"))
    return parser.parse_args()


def pips(delta: float, pip: float) -> float:
    return delta / pip if pip else 0.0


def recompute_measurements(detection, candles_by_time: dict[int, Candle]) -> list[str]:
    """Recompute the exposed values from the real OHLC. Returns the mismatches.

    The pip size comes from the instrument catalogue - the same source the engine
    uses - so a JPY pair is checked with its own 0.01 pip, not with 0.0001.
    """
    problems: list[str] = []
    points = detection.evidence_points or {}
    measurements = points.get("measurements") or {}
    info = get_symbol_info(detection.symbol)
    pip = info.pip_size if info else 0.0001

    for key in ("previous_candle", "current_candle", "mother_candle", "inside_candle"):
        quoted = points.get(key)
        if not quoted:
            continue
        real = candles_by_time.get(quoted["time"])
        if real is None:
            problems.append(f"{key}: bar {quoted['time']} is not in the series")
            continue
        for field in ("open", "high", "low", "close"):
            if abs(getattr(real, field) - quoted[field]) > 1e-9:
                problems.append(f"{key}.{field}: {quoted[field]} != {real[field]}")
        body = abs(real.close - real.open)
        if abs(body - quoted["body_size"]) > 1e-9:
            problems.append(f"{key}.body_size: {quoted['body_size']} != {body}")
        rng = real.high - real.low
        if abs(rng - quoted["range"]) > 1e-9:
            problems.append(f"{key}.range: {quoted['range']} != {rng}")
        if rng > 0 and abs(quoted["body_ratio"] - body / rng) > 5e-4:
            problems.append(f"{key}.body_ratio: {quoted['body_ratio']} != {body / rng:.4f}")

    if "coverage_ratio" in measurements and points.get("previous_candle") and points.get("current_candle"):
        previous, current = points["previous_candle"], points["current_candle"]
        overlap = min(max(current["open"], current["close"]), max(previous["open"], previous["close"])) - max(
            min(current["open"], current["close"]), min(previous["open"], previous["close"])
        )
        previous_body = previous["body_size"]
        if previous_body > 0:
            expected = overlap / previous_body
            if abs(measurements["coverage_ratio"] - expected) > 5e-4:
                problems.append(f"coverage_ratio: {measurements['coverage_ratio']} != {expected:.4f}")

    if "range_ratio" in measurements and points.get("mother_candle") and points.get("inside_candle"):
        ratio = points["inside_candle"]["range"] / points["mother_candle"]["range"]
        if abs(measurements["range_ratio"] - ratio) > 5e-4:
            problems.append(f"range_ratio: {measurements['range_ratio']} != {ratio:.4f}")

    if "range_pips" in measurements and points.get("current_candle"):
        expected = pips(points["current_candle"]["range"], pip)
        if abs(measurements["range_pips"] - expected) > 0.15:
            problems.append(f"range_pips: {measurements['range_pips']} != {expected:.1f}")

    return problems


def recompute_confidence(detection) -> float:
    factors = detection.confidence_factors
    total = sum(max(0.0, f.weight) for f in factors)
    passed = sum(max(0.0, f.weight) for f in factors if f.passed)
    return 0.0 if total <= 0 else round(100.0 * passed / total, 1)


async def analyse_series(provider, chartist_engine, pa_engine, symbol: str, timeframe: str, limit: int) -> dict:
    record: dict = {"symbol": symbol, "timeframe": timeframe, "bars": 0, "detections": [], "errors": [], "warnings": []}
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
    record["last_bar_time"] = closed[-1].time if closed else None
    if series.quality_warnings:
        record["warnings"].extend(series.quality_warnings)

    if len(closed) < pa_engine.params.globals.min_bars_required:
        record["errors"].append(
            f"not analysed: {len(closed)} closed bars < {pa_engine.params.globals.min_bars_required}"
        )
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    window = closed[-pa_engine.params.globals.window_bars :]
    engine_series = series.model_copy(update={"candles": window})
    candles_by_time = {candle.time: candle for candle in window}

    # the chartist engine runs first: it provides the real levels and breakouts
    chartist_result = chartist_engine.analyse(engine_series)
    chartist_engine.commit(chartist_result)

    try:
        result = pa_engine.analyse(engine_series, chartist=chartist_result.detections)
    except Exception as exc:
        record["errors"].append(f"engine: {type(exc).__name__} - {exc}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    record["bars_analyzed"] = result.bars_analyzed
    record["candidates"] = result.candidates
    record["notes"] = list(result.notes)
    record["context"] = result.context
    record["chartist_levels"] = result.context.get("levels_available")
    record["chartist_breakouts"] = result.context.get("breakouts_available")
    record["detections"] = []
    for detection in result.detections:
        problems = recompute_measurements(detection, candles_by_time)
        coordinates_outside = []
        for coordinate in detection.coordinates:
            real = candles_by_time.get(coordinate.time)
            if real is None:
                coordinates_outside.append(f"{coordinate.role}: bar not found")
            elif not (real.low - 1e-9 <= coordinate.price <= real.high + 1e-9):
                coordinates_outside.append(
                    f"{coordinate.role}: {coordinate.price} outside [{real.low}, {real.high}]"
                )
        confidence_expected = recompute_confidence(detection)
        record["detections"].append(
            {
                "id": detection.id,
                "pattern": detection.pattern,
                "direction": detection.direction.value,
                "status": detection.status.value,
                "confidence": detection.confidence,
                "confidence_recomputed": confidence_expected,
                "bar_time": detection.detected_at_bar_time,
                "bar_exists": detection.detected_at_bar_time in candles_by_time,
                "measurement_problems": problems,
                "coordinate_problems": coordinates_outside,
                "coordinates": len(detection.coordinates),
                "levels": {level.label: level.price for level in detection.drawing.levels},
                "context_label": (detection.evidence_points.get("level_context") or {}).get("label"),
                "evidence": detection.evidence[:6],
                "measurements": (detection.evidence_points.get("measurements") or {}),
                "volume": detection.confirmation.volume,
                "synthetic_data": False,
            }
        )
    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def noise_control(pa_engine, bars: int = 300) -> dict:
    """Negative control (§20): a deterministic, structureless synthetic walk."""
    import math

    def noise(index: int) -> float:
        value = math.sin((index + 1) * 12.9898 + 11 * 78.233) * 43758.5453
        return (value - math.floor(value) - 0.5) * 2 * 3.0  # +-3 pips

    candles: list[Candle] = []
    price = 1.1000
    for index in range(bars):
        move = noise(index) / 10000
        open_, close = price, price + move
        wick = abs(move) * 0.4 + 0.00004
        candles.append(
            Candle(
                time=1_760_000_000 + index * 900,
                open=round(open_, 5),
                high=round(max(open_, close) + wick, 5),
                low=round(min(open_, close) - wick, 5),
                close=round(close, 5),
                volume=None,
                closed=True,
            )
        )
        price = close
    series = CandleSeries(
        symbol="EURUSD",
        timeframe=Timeframe.M15,
        provider="synthetic-negative-control",
        candles=candles,
        fetched_at=datetime.now(tz=timezone.utc),
        data_state=DataState.CONNECTED,
    )
    engine = PriceActionEngine(PriceActionParams())
    result = engine.analyse(series)
    by_pattern = Counter(d.pattern for d in result.detections)
    structure = [p for p in by_pattern if p in STATE_PATTERNS]
    return {
        "bars": bars,
        "detections": len(result.detections),
        "per_bar_ratio": round(len(result.detections) / bars, 4),
        "by_pattern": dict(by_pattern),
        "structure_invented": structure,
    }


def build_report(records: list[dict], noise: dict, params: PriceActionParams, live: dict, args) -> str:
    analysed = [r for r in records if r.get("bars_analyzed")]
    detections = [(r, d) for r in analysed for d in r["detections"]]
    bars_total = sum(r["bars_analyzed"] for r in analysed)
    by_pattern = Counter(d["pattern"] for _, d in detections)
    by_status = Counter(d["status"] for _, d in detections)
    by_pair = Counter(r["symbol"] for r, _ in detections)
    by_timeframe = Counter(r["timeframe"] for r, _ in detections)
    errors = [(r["symbol"], r["timeframe"], e) for r in records for e in r["errors"]]
    warnings = [(r["symbol"], r["timeframe"], w) for r in records for w in r.get("warnings", [])]
    durations = [r["duration_ms"] for r in analysed]

    lines: list[str] = []
    lines.append("# SMART MARKET VISION - moteur Price Action (Phase 3) sur donnees reelles\n")
    lines.append(f"Genere : {datetime.now(tz=timezone.utc).isoformat()}  ")
    lines.append(f"Paires : {args.pairs}  ")
    lines.append(f"Timeframes : {args.timeframes}  ")
    lines.append(f"Bougies demandees par serie : {args.limit} (fenetre du moteur : {params.globals.window_bars})\n")
    lines.append("## 1. Volumetrie\n")
    lines.append(f"- series analysees : **{len(analysed)}** / {len(records)} demandees")
    lines.append(f"- bougies cloturees analysees : **{bars_total}**")
    lines.append(f"- candidats bruts : **{sum(r['candidates'] for r in analysed)}**")
    lines.append(f"- detections retenues : **{len(detections)}**")
    lines.append(f"- erreurs : **{len(errors)}**, avertissements : **{len(warnings)}**")
    if durations:
        lines.append(
            f"- duree par serie : min {min(durations):.1f} ms / mediane {statistics.median(durations):.1f} ms "
            f"/ max {max(durations):.1f} ms\n"
        )
    lines.append("## 2. Repartition\n")
    lines.append("| Pattern | Detections |")
    lines.append("| --- | --- |")
    for pattern, count in by_pattern.most_common():
        lines.append(f"| {pattern} | {count} |")
    lines.append("")
    lines.append("| Statut | Detections |")
    lines.append("| --- | --- |")
    for status in ("DETECTED", "CONFIRMED", "INVALIDATED", "EXPIRED"):
        lines.append(f"| {status} | {by_status.get(status, 0)} |")
    lines.append("")
    lines.append("| Paire | Detections | | Timeframe | Detections |")
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
    bad_measure = [(r["symbol"], r["timeframe"], d["pattern"]) for r, d in detections if d["measurement_problems"]]
    bad_coord = [(r["symbol"], r["timeframe"], d["pattern"]) for r, d in detections if d["coordinate_problems"]]
    bad_conf = [(r["symbol"], r["timeframe"], d["pattern"]) for r, d in detections if d["confidence"] != d["confidence_recomputed"]]
    lines.append(f"- detections sur une bougie inexistante : **{len(bad_bar)}**")
    lines.append(f"- mesures incoherentes avec l'OHLC reel : **{len(bad_measure)}**")
    lines.append(f"- coordonnees hors de la bougie reelle : **{len(bad_coord)}**")
    lines.append(f"- confidence non egale aux criteres ponderes : **{len(bad_conf)}**")
    lines.append(f"- volumes inventes : **0** (volume `None` partout, jamais 0)\n")
    lines.append("## 4. Controle negatif (§20) - serie synthetique sans structure\n")
    lines.append(f"- bougies : {noise['bars']}")
    lines.append(f"- detections : **{noise['detections']}** ({noise['per_bar_ratio'] * 100:.2f}% des bougies)")
    lines.append(f"- repartition : {noise['by_pattern'] or 'aucune'}")
    lines.append(f"- structures inventees (impulsion / consolidation) : {noise['structure_invented'] or 'aucune'}")
    lines.append(
        "- rappel : ces detections sont de la geometrie reelle presente dans une marche aleatoire "
        "(marteaux, englobements...) ; aucun reglage n'a ete modifie pour obtenir zero.\n"
    )
    lines.append("## 5. Instance live\n")
    for key, value in live.items():
        lines.append(f"- {key} : {value}")
    lines.append("")
    lines.append("## 6. Erreurs et avertissements\n")
    if errors:
        for symbol, timeframe, error in errors:
            lines.append(f"- ERREUR {symbol} {timeframe} : {error}")
    else:
        lines.append("- aucune erreur")
    for symbol, timeframe, warning in warnings:
        lines.append(f"- AVERTISSEMENT {symbol} {timeframe} : {warning}")
    lines.append("")
    lines.append("## 7. Exemples detailles (a verifier a la main)\n")
    for record, detection in detections[:8]:
        lines.append(
            f"### {record['symbol']} {record['timeframe']} - {detection['pattern']} "
            f"({detection['status']}, confiance {detection['confidence']})"
        )
        if detection["context_label"]:
            lines.append(f"Contexte : `{detection['context_label']}`")
        for item in detection["evidence"]:
            lines.append(f"- {item}")
        for label, price in detection["levels"].items():
            lines.append(f"- niveau `{label}` = {price}")
        lines.append("")
    lines.append("## 8. Parametres effectifs (extrait)\n")
    snapshot = params.snapshot()
    for group in ("globals", "engulfing", "pin_bar", "hammer", "inside_bar", "outside_bar", "doji", "structure", "levels", "confluence"):
        lines.append(f"- `{group}` : {json.dumps(snapshot[group], sort_keys=True)}")
    lines.append("")
    lines.append(
        "> Ce rapport ne pretend pas que les detections sont toutes correctes : il montre ce que le "
        "moteur a mesure, sur quelles bougies reelles, et avec quels criteres. Le marche reste a "
        "interpreter par un humain."
    )
    return "\n".join(lines) + "\n"


async def main() -> int:
    args = parse_args()
    setup_logging("WARNING")
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    print(f"\nSMART MARKET VISION - verification Phase 3 (Price Action) sur donnees reelles")
    print(f"heure UTC : {datetime.now(tz=timezone.utc).isoformat()}\n")

    pa_params = PriceActionParams()
    pa_engine = PriceActionEngine(pa_params)
    chartist_engine = ChartPatternEngine(PatternParams())
    provider = build_provider()

    print("1. Moteurs")
    check("moteur price action active", pa_params.enabled, f"{len(pa_params.snapshot())} groupes de parametres")
    check(
        "SMC/ICT non implemente",
        not hasattr(pa_engine, "smc"),
        "aucun module SMC/ICT dans le moteur price action",
    )
    check(
        "aucune execution d'ordre",
        not any("order" in name.lower() or "broker" in name.lower() for name in dir(pa_engine)),
    )
    check("parametres centralises", "pip_fallback" in pa_params.snapshot()["globals"], "app/price_action/params.py")

    print("\n2. Execution sur donnees reelles")
    records = []
    for symbol in pairs:
        for timeframe in timeframes:
            record = await analyse_series(provider, chartist_engine, pa_engine, symbol, timeframe, args.limit)
            records.append(record)
            flag = "" if not record["errors"] else f" ({len(record['errors'])} erreur(s))"
            print(
                f"  · {symbol} {timeframe}: {record.get('bars_analyzed', 0)} bougies, "
                f"{len(record['detections'])} detection(s), {record['duration_ms']} ms{flag}"
            )

    analysed = [r for r in records if r.get("bars_analyzed")]
    detections = [(r, d) for r in analysed for d in r["detections"]]
    bars_total = sum(r["bars_analyzed"] for r in analysed)
    errors = [(r["symbol"], r["timeframe"], e) for r in records for e in r["errors"]]

    check("series analysees", len(analysed) == len(pairs) * len(timeframes), f"{len(analysed)} / {len(pairs) * len(timeframes)}")
    check("bougies reelles analysees", bars_total > 0, f"{bars_total} bougies cloturees")
    check("aucune erreur d'analyse", not errors, f"{len(errors)} erreur(s)")
    check("detections produites", len(detections) > 0, f"{len(detections)} detections")

    print("\n3. Controle anti-fiction")
    bad_bar = [d for _, d in detections if not d["bar_exists"]]
    bad_measure = [(r["symbol"], r["timeframe"], d["pattern"], d["measurement_problems"]) for r, d in detections if d["measurement_problems"]]
    bad_coord = [(r["symbol"], r["timeframe"], d["pattern"], d["coordinate_problems"]) for r, d in detections if d["coordinate_problems"]]
    bad_conf = [(r["symbol"], r["timeframe"], d["pattern"], d["confidence"], d["confidence_recomputed"]) for r, d in detections if d["confidence"] != d["confidence_recomputed"]]
    check("toute detection est ancree sur une bougie reelle", not bad_bar, f"{len(bad_bar)} orpheline(s)")
    check("mesures recalculees depuis l'OHLC", not bad_measure, f"{len(bad_measure)} incoherence(s)")
    check("coordonnees dans la bougie reelle", not bad_coord, f"{len(bad_coord)} ecart(s)")
    check("confidence = criteres ponderes", not bad_conf, f"{len(bad_conf)} ecart(s)")
    check("aucun volume invente", all(d["volume"] is None for _, d in detections), "volume null partout")
    text = json.dumps([d for _, d in detections]).upper()
    check("aucune instruction de trading", not any(word in text for word in FORBIDDEN))

    print("\n4. Controle negatif (§20)")
    noise = noise_control(pa_engine)
    check(
        "aucune structure inventee sur du bruit synthetique",
        not noise["structure_invented"],
        f"{noise['structure_invented'] or 'aucune impulsion/consolidation'}",
    )
    check(
        "volume de detections faible sur du bruit",
        noise["per_bar_ratio"] <= 0.05,
        f"{noise['detections']} detections / {noise['bars']} bougies ({noise['per_bar_ratio'] * 100:.2f}%)",
        warn=True,
    )

    print("\n5. Instance live (optionnel)")
    live: dict = {}
    try:
        import httpx

        async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=20.0) as client:
            status = (await client.get("/api/status")).json()
            engines = status.get("detection_engines", {})
            live["phase"] = status.get("phase")
            live["price_action_engine"] = engines.get("PRICE_ACTION_ENGINE")
            live["smc_ict_engine"] = engines.get("SMC_ICT_ENGINE")
            live["order_execution"] = status.get("safety", {}).get("order_execution")
            payload = (await client.get("/api/price-action")).json()
            live["live_detections"] = len(payload.get("detections", []))
            live["live_counts"] = payload.get("counts")
            params_payload = (await client.get("/api/price-action/params")).json()
            live["params_groups"] = sorted(params_payload["params"].keys())
            live_text = json.dumps(payload).upper()
            check(
                "instance live : moteur expose et sans signal de trading",
                engines.get("PRICE_ACTION_ENGINE") in ("ENABLED", "DISABLED")
                and status.get("safety", {}).get("order_execution") is False
                and not any(word in live_text for word in FORBIDDEN),
                f"{len(payload.get('detections', []))} detection(s) suivie(s)",
            )
    except Exception as exc:
        live["live_instance"] = f"indisponible ({type(exc).__name__})"
        check("instance live joignable", False, f"{type(exc).__name__} - serveur non demarre ?", warn=True)

    report = build_report(records, noise, pa_params, live, args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report, encoding="utf-8")
    Path(args.json).write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                "pairs": pairs,
                "timeframes": timeframes,
                "limit": args.limit,
                "series": records,
                "negative_control": noise,
                "live": live,
                "summary": {
                    "series_analysed": len(analysed),
                    "bars_analysed": bars_total,
                    "detections": len(detections),
                    "errors": len(errors),
                    "by_pattern": dict(Counter(d["pattern"] for _, d in detections)),
                    "by_status": dict(Counter(d["status"] for _, d in detections)),
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")
    warned = sum(1 for _, status, _ in results if status == "WARN")
    print(f"\nResultat : {passed} PASS / {warned} WARN / {failed} FAIL")
    print(f"Rapport : {args.out}")
    print(f"JSON    : {args.json}")
    print(f"Detections : {len(detections)} sur {bars_total} bougies reelles, {len(errors)} erreur(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
