"""Data quality checks.

Values coming from the upstream feed are NEVER modified. Checks only produce
warnings attached to the payload (and stored with the candles) so the UI and
the future detection engines know exactly how trustworthy a series is.

Measured on the live feed (2026-09-29): the observed violation of
``high >= max(open, close)`` / ``low <= min(open, close)`` is below 0.08 pip,
which identifies it as a source rounding artefact rather than corrupt data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.market import CandleSeries

#: tolerated rounding error, expressed in pips, before a warning is raised
OHLC_ROUNDING_TOLERANCE_PIPS = 0.2
#: a bar older than this multiple of its timeframe is considered stale
STALE_FACTOR = 3


def check_ohlc_consistency(series: CandleSeries, digits: int, pip_size: float) -> list[str]:
    warnings: list[str] = []
    tolerance = OHLC_ROUNDING_TOLERANCE_PIPS * pip_size
    violations = 0
    worst = 0.0
    for candle in series.candles:
        upper = max(candle.open, candle.close)
        lower = min(candle.open, candle.close)
        delta_high = candle.high - upper
        delta_low = lower - candle.low
        worst = max(worst, -delta_high if delta_high < 0 else 0.0, -delta_low if delta_low < 0 else 0.0)
        if delta_high < -tolerance or delta_low < -tolerance:
            violations += 1
    if violations:
        warnings.append(
            f"{violations} bar(s) with OHLC rounding inconsistency "
            f"(max deviation {worst / pip_size:.3f} pip) - raw data kept unchanged"
        )
    return warnings


def check_timestamps(series: CandleSeries) -> list[str]:
    warnings: list[str] = []
    times = [c.time for c in series.candles]
    if times != sorted(times):
        warnings.append("timestamps are not strictly increasing")
    if len(set(times)) != len(times):
        warnings.append("duplicate timestamps detected")
    now = datetime.now(tz=timezone.utc)
    now_ts = int(now.timestamp())
    tf_seconds = series.timeframe.seconds
    future = [t for t in times if t > now_ts + 60]
    if future:
        warnings.append(f"{len(future)} bar(s) dated in the future")
    bar = series.candles[-1]
    age = now_ts - bar.time
    if age > tf_seconds * STALE_FACTOR:
        hours = age / 3600
        warnings.append(
            f"last bar is {hours:.1f}h old (expected every {series.timeframe.value}) "
            "- the market may be closed"
        )
    return warnings


def check_completeness(series: CandleSeries) -> list[str]:
    """Detect missing bars inside the returned window (weekend / holiday gaps)."""
    warnings: list[str] = []
    if len(series.candles) < 2:
        return warnings
    tf_seconds = series.timeframe.seconds
    gaps: list[tuple[int, int]] = []
    for previous, current in zip(series.candles, series.candles[1:]):
        missing = (current.time - previous.time) // tf_seconds - 1
        if missing > 0:
            gaps.append((previous.time, int(missing)))
    total_missing = sum(count for _, count in gaps)
    if not total_missing:
        return warnings

    if tf_seconds >= 86400:
        # Daily bars: weekend/holiday gaps are structural, not anomalies.
        long_gaps = [(start, count) for start, count in gaps if count > 5]
        if long_gaps:
            warnings.append(f"{len(long_gaps)} gap(s) longer than one week in the daily series")
        return warnings

    # A gap of up to ~3.5 days is the normal weekend (+ occasional holiday)
    # break of the Forex market; anything longer is a real hole in the feed.
    WEEKENDISH_SECONDS = int(3.5 * 86400)
    long_gaps = [g for g in gaps if (g[1] * tf_seconds) > WEEKENDISH_SECONDS]
    if long_gaps:
        warnings.append(
            f"{total_missing} missing bar(s) across {len(gaps)} gap(s); "
            f"{len(long_gaps)} gap(s) longer than 3.5 days - upstream feed hole to review"
        )
    return warnings


def analyse_series(series: CandleSeries, digits: int = 5, pip_size: float = 0.0001) -> CandleSeries:
    """Attach all quality warnings to the series (raw data left untouched)."""
    warnings = (
        check_timestamps(series)
        + check_ohlc_consistency(series, digits, pip_size)
        + check_completeness(series)
    )
    series.quality_warnings = list(dict.fromkeys(series.quality_warnings + warnings))
    return series
