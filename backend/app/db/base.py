"""Database engine / session management (SQLAlchemy 2.x).

SQLite today, PostgreSQL tomorrow: only ``DATABASE_URL`` changes. The models
avoid SQLite-only column types so the migration is a matter of one env var.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.logging_conf import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


def _prepare_sqlite_path(database_url: str) -> None:
    prefix = "sqlite+pysqlite:///"
    if database_url.startswith(prefix):
        raw = database_url[len(prefix):]
        if raw and raw != ":memory:" and not raw.startswith("file:"):
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine: Engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


#: columns added in Phase 2 to a table that may already exist in a Phase 1 database
_PHASE2_COLUMNS: dict[str, dict[str, str]] = {
    "pattern_detections": {
        "dedup_key": "VARCHAR(64)",
        "detected_at_bar_time": "INTEGER",
        "first_seen_at": "DATETIME",
        "last_updated_at": "DATETIME",
        "bars_in_window": "INTEGER",
        "parent_detection_id": "VARCHAR(64)",
        "evidence_points_json": "TEXT",
        "drawing_json": "TEXT",
        "parameters_json": "TEXT",
        "confidence_factors_json": "TEXT",
        "confirmation_json": "TEXT",
        "invalidation_json": "TEXT",
        "breakout_json": "TEXT",
        "retest_json": "TEXT",
        "watch_levels_json": "TEXT",
    }
}


def _apply_additive_migrations() -> None:
    """Add the Phase 2 columns to an existing database without losing a row.

    ``create_all`` never alters a table that already exists, so a Phase 1 file
    database would miss the new detection columns. They are added with plain
    ``ALTER TABLE ... ADD COLUMN``, which every row of Phase 1 (none) survives.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _PHASE2_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, sql_type in columns.items():
            if name in present:
                continue
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
            logger.info("Database migration: added %s.%s", table, name)


def init_db() -> None:
    """Create tables when missing, then apply additive migrations only."""
    from app.db import models  # noqa: F401  (register mappers)

    _apply_additive_migrations()
    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()
    logger.info("Database ready (%s)", "sqlite" if settings.is_sqlite else "postgresql")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
