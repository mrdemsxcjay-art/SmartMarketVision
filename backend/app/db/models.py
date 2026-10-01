"""Persistence models.

* ``candles``  : real OHLCV history used by the structure layer and by future
  back-testing of the detectors.
* ``market_events`` : audit trail of what the scanner observed (real events only).
* ``pattern_detections`` : reserved for phases 2-4. The table stays EMPTY in
  Phase 1 - no synthetic detection is ever written.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candle_identity"),
        Index("ix_candles_lookup", "symbol", "timeframe", "open_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    open_time: Mapped[int] = mapped_column(Integer, index=True)  # UTC epoch seconds
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed: Mapped[int] = mapped_column(Integer, default=1)  # 0/1, portable boolean
    provider: Mapped[str] = mapped_column(String(32))
    digits: Mapped[int] = mapped_column(Integer, default=5)
    quality_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


class MarketEventRow(Base):
    __tablename__ = "market_events"
    __table_args__ = (Index("ix_events_lookup", "symbol", "timeframe", "timestamp"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    timeframe: Mapped[str | None] = mapped_column(String(8), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class PatternDetectionRow(Base):
    """Chartist detections, stored once per formation and updated in place.

    The row keeps everything needed for later back-testing / replay / statistics:
    the evidence, the coordinates, the drawing, the parameters actually used and
    the full lifecycle (first seen, last update, breakout, retest).
    """

    __tablename__ = "pattern_detections"
    __table_args__ = (
        Index("ix_detections_lookup", "symbol", "timeframe", "timestamp"),
        Index("ix_detections_dedup", "dedup_key"),
        Index("ix_detections_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    detected_at_bar_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    category: Mapped[str] = mapped_column(String(24))
    pattern: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="DETECTED")
    source_engine: Mapped[str] = mapped_column(String(32), default="NONE")
    bars_in_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_detection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    coordinates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawing_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    breakout_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    retest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_levels_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScannerRunRow(Base):
    """One row per scanner tick, to prove the scanner really ran on real data."""

    __tablename__ = "scanner_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pairs_scanned: Mapped[int] = mapped_column(Integer, default=0)
    pairs_failed: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(32))
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfluenceRow(Base):
    """Phase 5 - one row per confluence, updated in place through its lifecycle.

    The row keeps the source events (with their real detection ids), the exact
    score breakdown, the explicit why / against lists and the expiration, so any
    score can be replayed and audited later. No probability, no forecast.
    """

    __tablename__ = "confluences"
    __table_args__ = (
        Index("ix_confluences_lookup", "symbol", "timeframe", "timestamp"),
        Index("ix_confluences_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    anchor_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    direction: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dimensions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    events_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    components_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    contradictions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    against_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    multi_timeframe_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)


class OpportunityRow(Base):
    """Phase 6 - one row per analytical opportunity, updated in place.

    BUY / SELL are ANALYTICAL directions observed by the engine. Nothing in this
    application can send an order: there is no broker, no execution surface.
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opportunities_lookup", "symbol", "timeframe", "timestamp"),
        Index("ix_opportunities_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    direction: Mapped[str] = mapped_column(String(16))  # BUY | SELL | WATCH | NO_TRADE
    state: Mapped[str] = mapped_column(String(24))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confluence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    no_trade_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watch_levels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    alert_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CaptureRow(Base):
    """Phase 7 - one real chart capture (a PNG of real candles, never a mock-up)."""

    __tablename__ = "captures"
    __table_args__ = (Index("ix_captures_lookup", "symbol", "timeframe", "timestamp"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    bar_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[str] = mapped_column(Text)
    telegram_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    digest: Mapped[str] = mapped_column(String(64), index=True)  # sha1 of the PNG
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candles_drawn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overlays_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="RENDERED")


class TelegramOutboxRow(Base):
    """Phase 8 - durable outbox: the scanner never waits for Telegram."""

    __tablename__ = "telegram_outbox"
    __table_args__ = (Index("ix_outbox_status", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    capture_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(8), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    provider_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
