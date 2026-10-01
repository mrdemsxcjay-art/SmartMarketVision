"""Repositories - the only layer that talks SQL."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.base import session_scope
from app.db.models import (
    CandleRow,
    CaptureRow,
    ConfluenceRow,
    MarketEventRow,
    OpportunityRow,
    PatternDetectionRow,
    ScannerRunRow,
    TelegramOutboxRow,
)
from app.logging_conf import get_logger
from app.schemas.events import MarketEvent, PatternDetection
from app.schemas.market import Candle, CandleSeries, Timeframe

logger = get_logger(__name__)


class CandleRepository:
    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def upsert_candles(self, series: CandleSeries, digits: int = 5) -> int:
        """Persist real bars only. Closed bars overwrite, forming bars update."""
        if not series.candles:
            return 0
        payload = [
            {
                "symbol": series.symbol,
                "timeframe": series.timeframe.value,
                "open_time": candle.time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "closed": 1 if candle.closed else 0,
                "provider": series.provider,
                "digits": digits,
                "quality_warnings": json.dumps(series.quality_warnings) if series.quality_warnings else None,
                "created_at": series.fetched_at,
                "updated_at": series.fetched_at,
            }
            for candle in series.candles
        ]
        with self._session_scope() as session:
            statement = sqlite_insert(CandleRow).values(payload)
            statement = statement.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "open_time"],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "volume": statement.excluded.volume,
                    "closed": statement.excluded.closed,
                    "provider": statement.excluded.provider,
                    "quality_warnings": statement.excluded.quality_warnings,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            session.execute(statement)
        return len(payload)

    def get_candles(self, symbol: str, timeframe: str, limit: int = 400, closed_only: bool = False) -> list[Candle]:
        with self._session_scope() as session:
            query = select(CandleRow).where(
                CandleRow.symbol == symbol.upper(),
                CandleRow.timeframe == timeframe.upper(),
            )
            if closed_only:
                query = query.where(CandleRow.closed == 1)
            query = query.order_by(CandleRow.open_time.desc()).limit(limit)
            rows = list(session.scalars(query))
        rows.reverse()
        return [
            Candle(
                time=row.open_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                closed=bool(row.closed),
            )
            for row in rows
        ]

    def get_series(self, symbol: str, timeframe: str, limit: int = 400) -> CandleSeries | None:
        candles = self.get_candles(symbol, timeframe, limit)
        if not candles:
            return None
        with self._session_scope() as session:
            provider = session.scalar(
                select(CandleRow.provider)
                .where(CandleRow.symbol == symbol.upper(), CandleRow.timeframe == timeframe.upper())
                .order_by(CandleRow.open_time.desc())
                .limit(1)
            )
            last_update = session.scalar(
                select(func.max(CandleRow.updated_at)).where(
                    CandleRow.symbol == symbol.upper(), CandleRow.timeframe == timeframe.upper()
                )
            )
        return CandleSeries(
            symbol=symbol.upper(),
            timeframe=Timeframe(timeframe.upper()),
            provider=provider or "unknown",
            candles=candles,
            fetched_at=last_update or datetime.now(tz=timezone.utc),
        )

    def count(self, symbol: str | None = None, timeframe: str | None = None) -> int:
        with self._session_scope() as session:
            query = select(func.count()).select_from(CandleRow)
            if symbol:
                query = query.where(CandleRow.symbol == symbol.upper())
            if timeframe:
                query = query.where(CandleRow.timeframe == timeframe.upper())
            return int(session.scalar(query) or 0)

    def coverage(self) -> list[dict]:
        with self._session_scope() as session:
            rows = session.execute(
                select(
                    CandleRow.symbol,
                    CandleRow.timeframe,
                    func.count().label("bars"),
                    func.min(CandleRow.open_time).label("first"),
                    func.max(CandleRow.open_time).label("last"),
                ).group_by(CandleRow.symbol, CandleRow.timeframe)
            ).all()
        return [
            {
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "bars": row.bars,
                "first_bar_utc": datetime.fromtimestamp(row.first, tz=timezone.utc).isoformat(),
                "last_bar_utc": datetime.fromtimestamp(row.last, tz=timezone.utc).isoformat(),
            }
            for row in rows
        ]

    def purge_older_than(self, days: int) -> int:
        cutoff = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp())
        with self._session_scope() as session:
            result = session.execute(delete(CandleRow).where(CandleRow.open_time < cutoff))
        return int(result.rowcount or 0)


#: hard ceiling for the stored event metadata (a row must stay small in SQLite)
METADATA_MAX_CHARS = 4000


def _bounded_metadata(metadata: dict | None, limit: int = METADATA_MAX_CHARS) -> str | None:
    """Serialise event metadata so the stored JSON is **always valid**.

    The previous implementation cut the serialised string at 4000 characters,
    which happened in the middle of a nested value: every long payload (all the
    price-action and SMC/ICT events) was stored as invalid JSON and the read-only
    route ``/api/events/recent`` raised ``JSONDecodeError``.

    This keeps the exact behaviour (bounded row size, whole payload when it fits)
    but shortens the **values** instead of the text: every string longer than the
    budget is cut and flagged, so the JSON stays parseable and the reader can see
    that a value was shortened. No event is dropped, no field is invented.
    """
    if not metadata:
        return None
    text = json.dumps(metadata, default=str)
    if len(text) <= limit:
        return text

    def shrink(value, budget: int):
        if isinstance(value, dict):
            return {key: shrink(item, budget) for key, item in value.items()}
        if isinstance(value, list):
            return [shrink(item, budget) for item in value]
        if isinstance(value, str) and len(value) > budget:
            return value[:budget] + "...[truncated]"
        return value

    for budget in (600, 300, 140, 60, 24):
        candidate = json.dumps(shrink(metadata, budget), default=str)
        if len(candidate) <= limit:
            return candidate
    # last resort: keep only the small scalar fields, never a broken document
    scalars = {k: v for k, v in metadata.items() if isinstance(v, (int, float, bool)) or v is None}
    scalars["_metadata_truncated"] = True
    return json.dumps(scalars, default=str)[:limit]


def _load_metadata(raw: str | None) -> dict:
    """Read one stored payload, tolerating rows written by the older code."""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        # legacy row: the string was cut in the middle by the Phase 1-4 writer
        return {"_malformed": True, "_raw_length": len(raw), "_note": "legacy truncated payload"}
    return loaded if isinstance(loaded, dict) else {"_value": loaded}


class EventRepository:
    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def save(self, event: MarketEvent) -> None:
        with self._session_scope() as session:
            session.add(
                MarketEventRow(
                    id=event.id,
                    symbol=event.symbol,
                    timeframe=event.timeframe.value if event.timeframe else None,
                    event_type=event.event_type.value,
                    timestamp=event.timestamp,
                    price=event.price,
                    source=event.source,
                    metadata_json=_bounded_metadata(event.metadata),
                )
            )

    def recent(self, limit: int = 50, symbol: str | None = None) -> list[dict]:
        with self._session_scope() as session:
            query = select(MarketEventRow).order_by(MarketEventRow.timestamp.desc()).limit(limit)
            if symbol:
                query = query.where(MarketEventRow.symbol == symbol.upper())
            rows = list(session.scalars(query))
        return [
            {
                "id": row.id,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "event_type": row.event_type,
                "timestamp": row.timestamp.isoformat(),
                "price": row.price,
                "source": row.source,
                "metadata": _load_metadata(row.metadata_json),
            }
            for row in rows
        ]

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(MarketEventRow)) or 0)


def _stable_identity(detection: PatternDetection) -> str:
    """Stable identity of one event inside its id group.

    Built from the values that describe the event itself (pattern, anchor candle,
    drawing, evidence) and **not** from the bookkeeping timestamps: a detection
    tracked over several scans must always map to the same row. Two detections that
    even this payload cannot tell apart are the same event for storage purposes.
    """
    drawing = detection.drawing.model_dump_json() if detection.drawing else ""
    payload = "|".join(
        (
            detection.pattern,
            str(detection.detected_at_bar_time),
            drawing,
            " :: ".join(detection.evidence),
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


class DetectionRepository:
    """Chartist detections: one row per formation, updated through its lifecycle."""

    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def save(self, detection: PatternDetection) -> None:
        """Insert or update (the same formation keeps the same row and id)."""
        self.save_many([detection])

    def save_many(self, detections: list[PatternDetection]) -> int:
        """Insert or update (the same formation keeps the same row and id).

        The batch is deduplicated **before** the inserts, because ``session.get``
        cannot see the pending INSERTs of the same transaction when the session runs
        with ``autoflush=False`` (the project setting): a duplicate primary key inside
        one batch used to reach SQLite and made the *whole* batch fail.

        Two detections that are the same event (same id **and** same stable content:
        pattern, anchor candle, drawing, evidence) are written once. Two detections
        that only share an id but describe different events are both written: the
        stored primary key of such a pair is disambiguated from its content, so no
        batch can ever produce two INSERTs of the same key. Nothing is dropped
        silently and no batch is lost.

        Returns the number of distinct rows written by this call.
        """
        if not detections:
            return 0
        unique: dict[tuple[str, str], PatternDetection] = {}
        for detection in detections:
            unique.setdefault((detection.id, _stable_identity(detection)), detection)

        per_id: dict[str, int] = {}
        for detection_id, _ in unique:
            per_id[detection_id] = per_id.get(detection_id, 0) + 1

        with self._session_scope() as session:
            for (detection_id, identity), detection in unique.items():
                row_id = detection_id if per_id[detection_id] == 1 else f"{detection_id}-{identity}"
                row = session.get(PatternDetectionRow, row_id)
                if row is None:
                    row = PatternDetectionRow(id=row_id)
                    session.add(row)
                self._fill(row, detection)
        return len(unique)

    @staticmethod
    def _fill(row: PatternDetectionRow, detection: PatternDetection) -> None:
        row.dedup_key = detection.dedup_key
        row.symbol = detection.symbol
        row.timeframe = detection.timeframe.value
        row.timestamp = detection.timestamp
        row.detected_at_bar_time = detection.detected_at_bar_time
        row.first_seen_at = detection.first_seen_at
        row.last_updated_at = detection.last_updated_at
        row.category = detection.category.value
        row.pattern = detection.pattern
        row.direction = detection.direction.value
        row.confidence = detection.confidence
        row.status = detection.status.value
        row.source_engine = detection.source_engine.value
        row.bars_in_window = detection.bars_in_window
        row.parent_detection_id = detection.parent_detection_id
        row.evidence_json = json.dumps(detection.evidence)
        row.evidence_points_json = json.dumps(detection.evidence_points, default=str)
        row.watch_levels_json = json.dumps(
            [level.model_dump(mode="json") for level in detection.watch_levels], default=str
        )
        row.coordinates_json = json.dumps(
            [c.model_dump(mode="json") for c in detection.coordinates]
        )
        row.drawing_json = json.dumps(detection.drawing.model_dump(mode="json"))
        row.parameters_json = json.dumps(detection.parameters, default=str)
        row.confidence_factors_json = json.dumps(
            [f.model_dump(mode="json") for f in detection.confidence_factors]
        )
        row.confirmation_json = json.dumps(detection.confirmation.model_dump(mode="json"))
        row.invalidation_json = json.dumps(detection.invalidation.model_dump(mode="json"))
        row.breakout_json = json.dumps(
            detection.breakout.model_dump(mode="json") if detection.breakout else None
        )
        row.retest_json = json.dumps(detection.retest.model_dump(mode="json") if detection.retest else None)
        row.notes_json = json.dumps(detection.notes)

    # ------------------------------------------------------------- reading
    def get(self, detection_id: str) -> dict | None:
        with self._session_scope() as session:
            row = session.get(PatternDetectionRow, detection_id)
            return self._to_dict(row) if row else None

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        pattern: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        category: str | None = None,
    ) -> list[dict]:
        with self._session_scope() as session:
            statement = select(PatternDetectionRow)
            if category:
                statement = statement.where(PatternDetectionRow.category == category.upper())
            if symbol:
                statement = statement.where(PatternDetectionRow.symbol == symbol.upper())
            if timeframe:
                statement = statement.where(PatternDetectionRow.timeframe == timeframe.upper())
            if pattern:
                statement = statement.where(PatternDetectionRow.pattern == pattern.upper())
            if status:
                statement = statement.where(PatternDetectionRow.status == status.upper())
            if since:
                statement = statement.where(PatternDetectionRow.timestamp >= since)
            statement = statement.order_by(PatternDetectionRow.timestamp.desc()).limit(max(1, min(limit, 500)))
            return [self._to_dict(row) for row in session.scalars(statement)]

    def by_status(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(PatternDetectionRow.status, func.count()).group_by(PatternDetectionRow.status)
            ).all()
            return {status: int(count) for status, count in rows}

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(PatternDetectionRow)) or 0)

    def count_by_pattern(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(PatternDetectionRow.pattern, func.count()).group_by(PatternDetectionRow.pattern)
            ).all()
            return {pattern: int(count) for pattern, count in rows}

    @staticmethod
    def _to_dict(row: PatternDetectionRow) -> dict:
        def load(value: str | None):
            if not value:
                return None
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                return None

        return {
            "id": row.id,
            "dedup_key": row.dedup_key,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "timestamp": _iso_utc(row.timestamp),
            "detected_at_bar_time": row.detected_at_bar_time,
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
            "category": row.category,
            "pattern": row.pattern,
            "direction": row.direction,
            "confidence": row.confidence,
            "status": row.status,
            "source_engine": row.source_engine,
            "bars_in_window": row.bars_in_window,
            "evidence": load(row.evidence_json) or [],
            "evidence_points": load(row.evidence_points_json) or {},
            "watch_levels": load(row.watch_levels_json) or [],
            "coordinates": load(row.coordinates_json) or [],
            "drawing": load(row.drawing_json),
            "parameters": load(row.parameters_json) or {},
            "confidence_factors": load(row.confidence_factors_json) or [],
            "confirmation": load(row.confirmation_json),
            "invalidation": load(row.invalidation_json),
            "breakout": load(row.breakout_json),
            "retest": load(row.retest_json),
            "notes": load(row.notes_json) or [],
        }


class ConfluenceRepository:
    """Phase 5 - confluences, updated in place through their lifecycle.

    Same defensive batch rule as :class:`DetectionRepository`: the batch is
    deduplicated before the inserts, so one duplicate identity can never make a
    whole batch fail and no confluence is silently dropped.
    """

    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def save_many(self, groups: list) -> int:
        if not groups:
            return 0
        unique: dict[tuple[str, str], object] = {}
        for group in groups:
            unique.setdefault((group.id, _confluence_identity(group)), group)
        per_id: dict[str, int] = {}
        for group_id, _ in unique:
            per_id[group_id] = per_id.get(group_id, 0) + 1

        with self._session_scope() as session:
            for (group_id, identity), group in unique.items():
                row_id = group_id if per_id[group_id] == 1 else f"{group_id}-{identity}"
                row = session.get(ConfluenceRow, row_id)
                if row is None:
                    row = ConfluenceRow(id=row_id)
                    session.add(row)
                _fill_confluence(row, group)
        return len(unique)

    def get(self, group_id: str) -> dict | None:
        with self._session_scope() as session:
            row = session.get(ConfluenceRow, group_id)
            return _confluence_dict(row) if row else None

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        state: str | None = None,
        direction: str | None = None,
    ) -> list[dict]:
        with self._session_scope() as session:
            statement = select(ConfluenceRow)
            if symbol:
                statement = statement.where(ConfluenceRow.symbol == symbol.upper())
            if timeframe:
                statement = statement.where(ConfluenceRow.timeframe == timeframe.upper())
            if state:
                statement = statement.where(ConfluenceRow.state == state.upper())
            if direction:
                statement = statement.where(ConfluenceRow.direction == direction.upper())
            statement = statement.order_by(ConfluenceRow.timestamp.desc()).limit(max(1, min(limit, 500)))
            return [_confluence_dict(row) for row in session.scalars(statement)]

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(ConfluenceRow)) or 0)

    def count_by_state(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(ConfluenceRow.state, func.count()).group_by(ConfluenceRow.state)
            ).all()
        return {state: int(total) for state, total in rows}


class OpportunityRepository:
    """Phase 6 - opportunities (analytical directions, never orders)."""

    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def save_many(self, opportunities: list) -> int:
        if not opportunities:
            return 0
        unique: dict[tuple[str, str], object] = {}
        for item in opportunities:
            unique.setdefault((item.id, _opportunity_identity(item)), item)
        per_id: dict[str, int] = {}
        for opportunity_id, _ in unique:
            per_id[opportunity_id] = per_id.get(opportunity_id, 0) + 1

        with self._session_scope() as session:
            for (opportunity_id, identity), item in unique.items():
                row_id = opportunity_id if per_id[opportunity_id] == 1 else f"{opportunity_id}-{identity}"
                row = session.get(OpportunityRow, row_id)
                if row is None:
                    row = OpportunityRow(id=row_id)
                    session.add(row)
                _fill_opportunity(row, item)
        return len(unique)

    def get(self, opportunity_id: str) -> dict | None:
        with self._session_scope() as session:
            row = session.get(OpportunityRow, opportunity_id)
            return _opportunity_dict(row) if row else None

    def history(
        self,
        limit: int = 100,
        symbol: str | None = None,
        timeframe: str | None = None,
        direction: str | None = None,
        state: str | None = None,
    ) -> list[dict]:
        with self._session_scope() as session:
            statement = select(OpportunityRow)
            if symbol:
                statement = statement.where(OpportunityRow.symbol == symbol.upper())
            if timeframe:
                statement = statement.where(OpportunityRow.timeframe == timeframe.upper())
            if direction:
                statement = statement.where(OpportunityRow.direction == direction.upper())
            if state:
                statement = statement.where(OpportunityRow.state == state.upper())
            statement = statement.order_by(OpportunityRow.timestamp.desc()).limit(max(1, min(limit, 500)))
            return [_opportunity_dict(row) for row in session.scalars(statement)]

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(OpportunityRow)) or 0)

    def count_by_direction(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(OpportunityRow.direction, func.count()).group_by(OpportunityRow.direction)
            ).all()
        return {direction: int(total) for direction, total in rows}

    def count_by_state(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(OpportunityRow.state, func.count()).group_by(OpportunityRow.state)
            ).all()
        return {state: int(total) for state, total in rows}

    def latest_alert_for(self, alert_key: str) -> dict | None:
        """Most recent opportunity sharing an anti-spam key (cooldown lookup)."""
        with self._session_scope() as session:
            row = session.scalar(
                select(OpportunityRow)
                .where(OpportunityRow.alert_key == alert_key)
                .order_by(OpportunityRow.timestamp.desc())
                .limit(1)
            )
            return _opportunity_dict(row) if row else None


class CaptureRepository:
    """Phase 7 - real chart captures, deduplicated by content digest."""

    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def save(self, capture: dict) -> None:
        with self._session_scope() as session:
            row = session.get(CaptureRow, capture["id"])
            if row is None:
                row = CaptureRow(id=capture["id"])
                session.add(row)
            for key, value in capture.items():
                if hasattr(row, key) and key != "id":
                    setattr(row, key, value)

    def get(self, capture_id: str) -> dict | None:
        with self._session_scope() as session:
            row = session.get(CaptureRow, capture_id)
            return _capture_dict(row) if row else None

    def get_by_digest(self, digest: str) -> dict | None:
        with self._session_scope() as session:
            row = session.scalar(select(CaptureRow).where(CaptureRow.digest == digest).limit(1))
            return _capture_dict(row) if row else None

    def history(
        self,
        limit: int = 50,
        symbol: str | None = None,
        opportunity_id: str | None = None,
    ) -> list[dict]:
        with self._session_scope() as session:
            statement = select(CaptureRow)
            if symbol:
                statement = statement.where(CaptureRow.symbol == symbol.upper())
            if opportunity_id:
                statement = statement.where(CaptureRow.opportunity_id == opportunity_id)
            statement = statement.order_by(CaptureRow.timestamp.desc()).limit(max(1, min(limit, 200)))
            return [_capture_dict(row) for row in session.scalars(statement)]

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(CaptureRow)) or 0)


class TelegramOutboxRepository:
    """Phase 8 - durable queue between the scanner and the Telegram API."""

    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def enqueue(self, entry: dict) -> bool:
        """Insert one alert. Returns False when the alert id already exists."""
        with self._session_scope() as session:
            if session.get(TelegramOutboxRow, entry["id"]) is not None:
                return False
            session.add(TelegramOutboxRow(**entry))
            return True

    def get(self, entry_id: str) -> dict | None:
        with self._session_scope() as session:
            row = session.get(TelegramOutboxRow, entry_id)
            return _outbox_dict(row) if row else None

    def next_pending(self, limit: int = 10) -> list[dict]:
        now = datetime.now(tz=timezone.utc)
        with self._session_scope() as session:
            statement = (
                select(TelegramOutboxRow)
                .where(TelegramOutboxRow.status.in_(("QUEUED", "RETRYING")))
                .where(
                    (TelegramOutboxRow.next_attempt_at.is_(None))
                    | (TelegramOutboxRow.next_attempt_at <= now)
                )
                .order_by(TelegramOutboxRow.created_at.asc())
                .limit(limit)
            )
            return [_outbox_dict(row) for row in session.scalars(statement)]

    def mark(self, entry_id: str, **fields) -> None:
        with self._session_scope() as session:
            row = session.get(TelegramOutboxRow, entry_id)
            if row is None:
                return
            for key, value in fields.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(tz=timezone.utc)

    def history(
        self,
        limit: int = 50,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict]:
        with self._session_scope() as session:
            statement = select(TelegramOutboxRow)
            if status:
                statement = statement.where(TelegramOutboxRow.status == status.upper())
            if symbol:
                statement = statement.where(TelegramOutboxRow.symbol == symbol.upper())
            statement = statement.order_by(TelegramOutboxRow.created_at.desc()).limit(max(1, min(limit, 500)))
            return [_outbox_dict(row) for row in session.scalars(statement)]

    def count_by_status(self) -> dict[str, int]:
        with self._session_scope() as session:
            rows = session.execute(
                select(TelegramOutboxRow.status, func.count()).group_by(TelegramOutboxRow.status)
            ).all()
        return {status: int(total) for status, total in rows}

    def count(self) -> int:
        with self._session_scope() as session:
            return int(session.scalar(select(func.count()).select_from(TelegramOutboxRow)) or 0)

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max(1, days))
        with self._session_scope() as session:
            result = session.execute(
                delete(TelegramOutboxRow).where(TelegramOutboxRow.created_at < cutoff)
            )
            return int(result.rowcount or 0)


# --------------------------------------------------------------- serialisers
def _confluence_identity(group) -> str:
    """Stable identity of one confluence inside its id group (content based)."""
    payload = "|".join(
        (
            group.direction,
            str(group.window_end),
            ",".join(sorted(event.id for event in group.events)),
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _fill_confluence(row: ConfluenceRow, group) -> None:
    row.dedup_key = group.dedup_key
    row.signature = group.signature
    row.symbol = group.symbol
    row.timeframe = group.timeframe
    row.timestamp = group.updated_at or row.timestamp
    row.first_seen_at = group.created_at
    row.last_updated_at = group.updated_at
    row.anchor_time = group.anchor_time
    row.window_start = group.window_start
    row.window_end = group.window_end
    row.expires_at = group.expires_at
    row.direction = group.direction
    row.state = group.state
    row.score = group.score
    row.max_score = group.max_score
    row.dimensions_json = json.dumps(group.dimensions)
    row.events_json = json.dumps([event.model_dump(mode="json") for event in group.events])
    row.components_json = json.dumps([item.model_dump(mode="json") for item in group.components])
    row.contradictions_json = json.dumps([item.model_dump(mode="json") for item in group.contradictions])
    row.why_json = json.dumps(group.why)
    row.against_json = json.dumps(group.against)
    row.multi_timeframe_json = json.dumps(group.multi_timeframe)
    row.reference_price = group.reference_price
    row.generation = group.generation


def _confluence_dict(row: ConfluenceRow) -> dict:
    load = _load_metadata
    return {
        "id": row.id,
        "dedup_key": row.dedup_key,
        "signature": row.signature,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "timestamp": _iso_utc(row.timestamp),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
        "anchor_time": row.anchor_time,
        "window_start": row.window_start,
        "window_end": row.window_end,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "direction": row.direction,
        "state": row.state,
        "score": row.score,
        "max_score": row.max_score,
        "dimensions": load(row.dimensions_json) if row.dimensions_json else [],
        "events": load(row.events_json) if row.events_json else [],
        "components": load(row.components_json) if row.components_json else [],
        "contradictions": load(row.contradictions_json) if row.contradictions_json else [],
        "why": load(row.why_json) if row.why_json else [],
        "against": load(row.against_json) if row.against_json else [],
        "multi_timeframe": load(row.multi_timeframe_json) if row.multi_timeframe_json else [],
        "reference_price": row.reference_price,
        "generation": row.generation,
    }


def _opportunity_identity(item) -> str:
    payload = "|".join((item.direction, str(item.created_at), item.confluence_id or "", ",".join(item.evidence[:2])))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _fill_opportunity(row: OpportunityRow, item) -> None:
    row.dedup_key = item.dedup_key
    row.symbol = item.symbol
    row.timeframe = item.timeframe
    row.timestamp = item.updated_at or row.timestamp
    row.first_seen_at = item.created_at
    row.last_updated_at = item.updated_at
    row.direction = item.direction
    row.state = item.state
    row.score = item.score
    row.max_score = item.max_score
    row.confluence_id = item.confluence_id
    row.reference_price = item.reference_price
    row.conditions_json = json.dumps([condition.model_dump(mode="json") for condition in item.conditions])
    row.evidence_json = json.dumps(item.evidence)
    row.no_trade_reason = item.no_trade_reason
    row.watch_levels_json = json.dumps([level.model_dump(mode="json") for level in item.watch_levels])
    row.created_at = item.created_at
    row.expires_at = item.expires_at
    row.generation = item.generation
    row.alert_key = item.alert_key


def _opportunity_dict(row: OpportunityRow) -> dict:
    load = _load_metadata
    return {
        "id": row.id,
        "dedup_key": row.dedup_key,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "timestamp": _iso_utc(row.timestamp),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
        "direction": row.direction,
        "state": row.state,
        "score": row.score,
        "max_score": row.max_score,
        "confluence_id": row.confluence_id,
        "reference_price": row.reference_price,
        "conditions": load(row.conditions_json) if row.conditions_json else [],
        "evidence": load(row.evidence_json) if row.evidence_json else [],
        "no_trade_reason": row.no_trade_reason,
        "watch_levels": load(row.watch_levels_json) if row.watch_levels_json else [],
        "created_at": _iso_utc(row.created_at),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "generation": row.generation,
        "alert_key": row.alert_key,
    }


def _capture_dict(row: CaptureRow) -> dict:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "timestamp": _iso_utc(row.timestamp),
        "bar_time": row.bar_time,
        "path": row.path,
        "telegram_path": row.telegram_path,
        "digest": row.digest,
        "width": row.width,
        "height": row.height,
        "size_bytes": row.size_bytes,
        "candles_drawn": row.candles_drawn,
        "overlays": _load_metadata(row.overlays_json) if row.overlays_json else {},
        "state": row.state,
    }


def _iso_utc(value: datetime | None) -> str | None:
    """ISO timestamp, always timezone-aware.

    SQLite gives back naive datetimes; every consumer (dashboard, API, tests,
    dispatcher) deserves the same, unambiguous value, so a naive value is stamped
    as UTC - the timezone the whole application writes in.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _outbox_dict(row: TelegramOutboxRow) -> dict:
    return {
        "id": row.id,
        "alert_id": row.alert_id,
        "opportunity_id": row.opportunity_id,
        "capture_id": row.capture_id,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "event_type": row.event_type,
        "message": row.message,
        "caption": row.caption,
        "status": row.status,
        "mode": row.mode,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "last_error": row.last_error,
        "next_attempt_at": _iso_utc(row.next_attempt_at),
        "created_at": _iso_utc(row.created_at),
        "updated_at": _iso_utc(row.updated_at),
        "sent_at": _iso_utc(row.sent_at),
        "provider_message_id": row.provider_message_id,
    }


class ScannerRunRepository:
    def __init__(self, session_factory=session_scope) -> None:
        self._session_scope = session_factory

    def start(self, provider: str) -> int:
        with self._session_scope() as session:
            row = ScannerRunRow(provider=provider, started_at=datetime.now(tz=timezone.utc))
            session.add(row)
            session.flush()
            return int(row.id)

    def finish(self, run_id: int, pairs_scanned: int, pairs_failed: int, errors: list[str]) -> None:
        with self._session_scope() as session:
            row = session.get(ScannerRunRow, run_id)
            if row is None:
                return
            row.finished_at = datetime.now(tz=timezone.utc)
            row.pairs_scanned = pairs_scanned
            row.pairs_failed = pairs_failed
            row.errors_json = json.dumps(errors)[:4000] if errors else None

    def last(self) -> dict | None:
        with self._session_scope() as session:
            row = session.scalar(select(ScannerRunRow).order_by(ScannerRunRow.id.desc()).limit(1))
        if row is None:
            return None
        return {
            "id": row.id,
            "started_at": row.started_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "pairs_scanned": row.pairs_scanned,
            "pairs_failed": row.pairs_failed,
            "provider": row.provider,
            "errors": json.loads(row.errors_json) if row.errors_json else [],
        }
