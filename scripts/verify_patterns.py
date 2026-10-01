#!/usr/bin/env python3
"""Real-data run of the chartist engine (Phase 2, criterion "donnees reelles").

This script feeds the engine REAL Forex candles (the same provider as the
dashboard uses) and reports what was detected - nothing else:

* how many closed bars were analysed, per pair and timeframe;
* every detection, with its status, confidence and its measurable evidence;
* breakdowns by pattern / pair / timeframe;
* the errors and the timings.

It deliberately does NOT claim that the detected patterns are correct: a
detection is only the output of explicit, reproducible criteria. The report is
written to ``reports/`` (markdown + JSON) so a human can check each case against
the real prices.

Usage::

    cd backend && python3 ../scripts/verify_patterns.py                  # default pairs
    cd backend && python3 ../scripts/verify_patterns.py --pairs EURUSD,USDJPY --timeframes M15,H1
    cd backend && python3 ../scripts/verify_patterns.py --limit 800 --out ../reports/run.md
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
from app.patterns.engine import ChartPatternEngine  # noqa: E402
from app.patterns.params import PatternParams  # noqa: E402
from app.providers.registry import build_provider  # noqa: E402
from app.schemas.market import Timeframe  # noqa: E402

DEFAULT_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
DEFAULT_TIMEFRAMES = ["M15", "H1", "H4"]
STATUS_ORDER = ["DETECTED", "CONFIRMED", "INVALIDATED", "EXPIRED"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chartist engine on real Forex data")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="closed bars requested per series (default = the engine window, as in production)",
    )
    parser.add_argument("--out", default=str(ROOT / "reports" / "patterns_real_data.md"))
    parser.add_argument("--json", default=str(ROOT / "reports" / "patterns_real_data.json"))
    parser.add_argument("--examples", type=int, default=6, help="how many detections are detailed in the report")
    return parser.parse_args()


def human(value: float, digits: int = 5) -> str:
    return f"{value:.{digits}f}"


async def analyse_series(engine: ChartPatternEngine, provider, symbol: str, timeframe: str, limit: int) -> dict:
    """Fetch real candles and run the engine; never invents a single bar."""
    record: dict = {"symbol": symbol, "timeframe": timeframe, "bars": 0, "detections": [], "errors": []}
    started = time.perf_counter()
    try:
        series = await provider.get_candles(symbol, Timeframe(timeframe), limit=limit)
    except Exception as exc:  # provider outage: reported, never worked around
        record["errors"].append(f"provider: {type(exc).__name__} - {exc}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    closed = [candle for candle in series.candles if candle.closed]
    record["provider"] = series.provider
    record["data_state"] = series.data_state.value
    record["bars"] = len(closed)
    record["last_bar_time"] = closed[-1].time if closed else None
    if series.quality_warnings:
        record["quality_warnings"] = series.quality_warnings

    if len(closed) < engine.params.globals.min_bars_required:
        record["errors"].append(
            f"not analysed: {len(closed)} closed bars < {engine.params.globals.min_bars_required}"
        )
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    window = closed[-engine.params.globals.window_bars :]
    engine_series = series.model_copy(update={"candles": window})
    try:
        result = engine.analyse(engine_series)
    except Exception as exc:  # a detector crash must be visible in the report
        record["errors"].append(f"engine: {type(exc).__name__} - {exc}")
        record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return record

    record["bars_analyzed"] = result.bars_analyzed
    record["pivots"] = result.pivots
    record["candidates"] = result.candidates
    record["notes"] = list(result.notes)
    record["detections"] = [
        {
            "id": detection.id,
            "pattern": detection.pattern,
            "direction": detection.direction.value,
            "status": detection.status.value,
            "confidence": detection.confidence,
            "bar_time": detection.detected_at_bar_time,
            "evidence": detection.evidence,
            "evidence_points": detection.evidence_points,
            "criteria": [
                {"criterion": f.criterion, "passed": f.passed, "detail": f.detail}
                for f in detection.confidence_factors
            ],
        }
        for detection in result.detections
    ]
    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def build_report(records: list[dict], params: PatternParams, args: argparse.Namespace) -> str:
    generated = datetime.now(tz=timezone.utc).isoformat()
    analysed = [r for r in records if r.get("bars_analyzed")]
    detections = [(r, d) for r in analysed for d in r["detections"]]
    bars_total = sum(r["bars_analyzed"] for r in analysed)

    by_pattern = Counter(d["pattern"] for _, d in detections)
    by_status = Counter(d["status"] for _, d in detections)
    by_pair = Counter(r["symbol"] for r, _ in detections)
    by_timeframe = Counter(r["timeframe"] for r, _ in detections)
    by_pattern_status = Counter((d["pattern"], d["status"]) for _, d in detections)
    durations = [r["duration_ms"] for r in analysed]
    errors = [(r["symbol"], r["timeframe"], message) for r in records for message in r.get("errors", [])]

    lines: list[str] = []
    add = lines.append
    add("# Chartist engine - run on real Forex data")
    add("")
    add(f"* generated (UTC): {generated}")
    add(f"* provider: `{analysed[0]['provider'] if analysed else 'n/a'}`")
    add(f"* pairs: {', '.join(sorted({r['symbol'] for r in records}))}")
    add(f"* timeframes: {', '.join(sorted({r['timeframe'] for r in records}))}")
    add(f"* closed bars requested per series: {args.limit}")
    add("")
    add("> This report lists what the engine computed from real OHLC. It is **not** a")
    add("> claim that every detection is a valid trading pattern: each one is only the")
    add("> result of the criteria listed with it, and must be reviewed by a human.")
    add("")

    add("## 1. Volume analysed")
    add("")
    add("| series analysed | closed bars analysed | detections | errors |")
    add("|---|---|---|---|")
    add(f"| {len(analysed)}/{len(records)} | {bars_total} | {len(detections)} | {len(errors)} |")
    add("")

    add("## 2. Detections by pattern")
    add("")
    if by_pattern:
        add("| pattern | count | DETECTED | CONFIRMED | INVALIDATED | EXPIRED |")
        add("|---|---|---|---|---|---|")
        for pattern, count in by_pattern.most_common():
            cells = [by_pattern_status.get((pattern, status), 0) for status in STATUS_ORDER]
            add(f"| {pattern} | {count} | " + " | ".join(str(c) for c in cells) + " |")
    else:
        add("_no detection at all on this run_")
    add("")

    add("## 3. Detections by pair and timeframe")
    add("")
    if detections:
        add("| pair | detections | timeframes |")
        add("|---|---|---|")
        for symbol, count in by_pair.most_common():
            frames = sorted({r["timeframe"] for r, _ in detections if r["symbol"] == symbol})
            add(f"| {symbol} | {count} | {', '.join(frames)} |")
        add("")
        add("| timeframe | detections |")
        add("|---|---|")
        for timeframe, count in by_timeframe.most_common():
            add(f"| {timeframe} | {count} |")
    else:
        add("_n/a_")
    add("")

    add("## 4. Series detail")
    add("")
    add("| pair | TF | closed bars | analysed | pivots | candidates | detections | ms |")
    add("|---|---|---|---|---|---|---|---|")
    for record in records:
        add(
            f"| {record['symbol']} | {record['timeframe']} | {record['bars']} | "
            f"{record.get('bars_analyzed', 0)} | {record.get('pivots', 0)} | "
            f"{record.get('candidates', 0)} | {len(record['detections'])} | {record['duration_ms']} |"
        )
    add("")

    add("## 5. Examples with their evidence (human review required)")
    add("")
    if detections:
        for record, detection in detections[: args.examples]:
            add(f"### {record['symbol']} {record['timeframe']} - {detection['pattern']} ({detection['status']})")
            add("")
            add(f"* direction: {detection['direction']}, confidence: {detection['confidence']}%")
            bar = detection["bar_time"]
            add(f"* last analysed bar (UTC): {datetime.fromtimestamp(bar, tz=timezone.utc) if bar else 'n/a'}")
            add("* criteria:")
            for criterion in detection["criteria"]:
                mark = "x" if criterion["passed"] else " "
                add(f"  * [{mark}] {criterion['criterion']} - {criterion['detail']}")
            add("* why (evidence):")
            for line in detection["evidence"][:8]:
                add(f"  * {line}")
            add("")
    else:
        add("_none_")
        add("")

    add("## 6. Errors and warnings")
    add("")
    if errors:
        for symbol, timeframe, message in errors:
            add(f"* {symbol} {timeframe}: {message}")
    else:
        add("* none")
    for record in records:
        for warning in record.get("quality_warnings", []):
            add(f"* {record['symbol']} {record['timeframe']} (provider warning): {warning}")
    add("")

    add("## 7. Timing (one series, single pass)")
    add("")
    if durations:
        add(
            f"* min {min(durations)} ms / median {statistics.median(durations)} ms / "
            f"max {max(durations)} ms over {len(durations)} series"
        )
    add("")

    add("## 8. Thresholds in force for this run")
    add("")
    add("```json")
    add(json.dumps(params.snapshot(), indent=2, sort_keys=True))
    add("```")
    add("")
    add("## 9. What this run does NOT prove")
    add("")
    add("* that the detections are profitable or even correct chartistically;")
    add("* that no pattern was missed (only that the criteria did not match);")
    add("* anything about price action / SMC-ICT: those engines are not implemented.")
    add("")
    return "\n".join(lines)


async def main() -> int:
    args = parse_args()
    setup_logging("WARNING")  # the report is the output, not the log stream

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    provider = build_provider()
    engine = ChartPatternEngine(PatternParams())

    print(f"Chartist engine on real data - provider={provider.name}, {len(pairs)} pairs x {len(timeframes)} timeframes")
    records: list[dict] = []
    for symbol in pairs:
        for timeframe in timeframes:
            record = await analyse_series(engine, provider, symbol, timeframe, args.limit)
            engine.clear()
            records.append(record)
            status = ", ".join(f"{d['pattern']}({d['status']})" for d in record["detections"]) or "-"
            print(
                f"  {symbol:7s} {timeframe:4s} bars={record['bars']:5d} "
                f"detections={len(record['detections']):2d} {status}"
            )
            for error in record["errors"]:
                print(f"    ! {error}")

    markdown = build_report(records, engine.params, args)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    json_path = Path(args.json)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                "provider": provider.name,
                "params": engine.params.snapshot(),
                "series": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    total = sum(len(r["detections"]) for r in records)
    print(f"\n{total} detection(s) on {sum(r.get('bars_analyzed', 0) for r in records)} real bars")
    print(f"report: {out_path}\ndata:   {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
