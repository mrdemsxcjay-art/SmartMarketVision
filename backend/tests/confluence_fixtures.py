"""Fixtures for the confluence tests (Phase 5).

Synthetic OHLC and synthetic *detections* are allowed **in tests only** - never in
production. The helpers here reuse the Phase 3 / Phase 4 fixtures so a confluence
test is built on the very same bar builders the other engines use.

A detection builder is provided per engine family (chartist, price action,
SMC/ICT) with the real field names those engines produce, so the normaliser is
exercised on realistic objects.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.events import (
    DetectionCategory,
    DetectionDirection,
    DetectionSource,
    DetectionStatus,
    DrawingLevel,
    DrawingSpec,
    PatternDetection,
    Timeframe,
)
from app.schemas.market import CandleSeries
from tests import price_action_fixtures as pa
from tests.price_action_fixtures import BarSpec  # re-exported: the bar builder of the project


def series(bars: list[pa.BarSpec], *, symbol: str = "EURUSD", timeframe: str = "M15") -> CandleSeries:
    return pa.series(bars, symbol=symbol, timeframe=timeframe)


def calm(count: int = 70, **kwargs) -> list[pa.BarSpec]:
    return pa.calm_bars(count, **kwargs)


def bar_time(index: int, timeframe: str = "M15") -> int:
    return pa.bar_time(index, timeframe)


def detection(
    *,
    detection_id: str,
    pattern: str,
    category: DetectionCategory,
    direction: str,
    timeframe: str = "M15",
    symbol: str = "EURUSD",
    time: int,
    price: float | None = None,
    status: DetectionStatus = DetectionStatus.DETECTED,
    confidence: float = 70.0,
    evidence: list[str] | None = None,
) -> PatternDetection:
    """One detection with the exact shape the real engines publish."""
    source = {
        DetectionCategory.CHARTISTE: DetectionSource.CHART_PATTERN_ENGINE,
        DetectionCategory.PRICE_ACTION: DetectionSource.PRICE_ACTION_ENGINE,
        DetectionCategory.SMC_ICT: DetectionSource.SMC_ICT_ENGINE,
    }[category]
    levels = [DrawingLevel(price=price, label="LEVEL", kind="LEVEL")] if price is not None else []
    return PatternDetection(
        id=detection_id,
        dedup_key=detection_id,
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        timestamp=datetime.now(tz=timezone.utc),
        category=category,
        pattern=pattern,
        direction=DetectionDirection(direction),
        confidence=confidence,
        status=status,
        source_engine=source,
        detected_at_bar_time=time,
        evidence=evidence or [f"{pattern} sur {time}"],
        evidence_points={"pattern": pattern},
        drawing=DrawingSpec(levels=levels),
        coordinates=[],
    )


# ---------------------------------------------------------------- SMC helpers
def bos(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="BOS", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def choch(detection_id: str, *, direction: str = "BEARISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="CHOCH", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def mss(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="MSS", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def sweep(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="LIQUIDITY_SWEEP", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def pool(detection_id: str, *, direction: str = "NEUTRAL", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="LIQUIDITY_POOL_ESTIMATE", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def fvg(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern=f"{direction}_FVG", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def order_block(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern=f"{direction}_ORDER_BLOCK", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def displacement(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="DISPLACEMENT", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


def premium_discount(detection_id: str, *, direction: str = "BULLISH", time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern="DISCOUNT", category=DetectionCategory.SMC_ICT,
        direction=direction, time=time, price=price, **kwargs,
    )


# -------------------------------------------------------- chartist helpers
def chartist(detection_id: str, pattern: str, *, direction: str, time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern=pattern, category=DetectionCategory.CHARTISTE,
        direction=direction, time=time, price=price, **kwargs,
    )


# ----------------------------------------------------- price action helpers
def price_action(detection_id: str, pattern: str, *, direction: str, time: int, price: float, **kwargs):
    return detection(
        detection_id=detection_id, pattern=pattern, category=DetectionCategory.PRICE_ACTION,
        direction=direction, time=time, price=price, **kwargs,
    )


def bullish_stack(time: int, *, price: float = 1.1, prefix: str = "fx") -> list[PatternDetection]:
    """A coherent bullish stack: structure + liquidity + imbalance + PA + chartist."""
    return [
        bos(f"{prefix}_bos", direction="BULLISH", time=time, price=price),
        sweep(f"{prefix}_sweep", direction="BULLISH", time=time, price=price),
        fvg(f"{prefix}_fvg", direction="BULLISH", time=time, price=price),
        price_action(f"{prefix}_pa", "BULLISH_ENGULFING", direction="BULLISH", time=time, price=price),
        chartist(f"{prefix}_ct", "SUPPORT", direction="BULLISH", time=time, price=price),
    ]

def bearish_stack(time: int, *, price: float = 1.1, prefix: str = "fx") -> list[PatternDetection]:
    """The mirrored detection set: five bearish detections, five dimensions."""
    return [
        choch(f"{prefix}_choch", direction="BEARISH", time=time, price=price),
        sweep(f"{prefix}_sweep", direction="BEARISH", time=time, price=price),
        fvg(f"{prefix}_fvg", direction="BEARISH", time=time, price=price),
        price_action(f"{prefix}_pa", "BEARISH_ENGULFING", direction="BEARISH", time=time, price=price),
        chartist(f"{prefix}_ct", "RESISTANCE", direction="BEARISH", time=time, price=price),
    ]


def state_value(name: str) -> str:
    """The real string value of a confluence state, by name."""
    from app.confluence.models import ConfluenceState

    return ConfluenceState[name].value
