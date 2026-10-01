"""Application configuration.

All configuration comes from environment variables / ``.env``.
Secrets (Telegram token) are NEVER logged or exposed through the API:
use :meth:`Settings.safe_snapshot` when reporting configuration state.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/
PROJECT_ROOT = BASE_DIR.parent  # repository root
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class ProviderName(str, Enum):
    """Available market data providers."""

    YAHOO = "yahoo"
    DISABLED = "disabled"  # explicit "no live data" mode -> DATA UNAVAILABLE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_title: str = "Smart Market Vision API"

    # ------------------------------------------------------------- database
    database_url: str = Field(default=f"sqlite+pysqlite:///{DEFAULT_DATA_DIR / 'smart_market_vision.db'}")
    database_retention_days: int = 120

    # --------------------------------------------------------- market data
    market_data_provider: ProviderName = ProviderName.YAHOO
    provider_timeout_seconds: float = 12.0
    provider_max_retries: int = 3
    provider_backoff_seconds: float = 0.5
    # Cache TTL per timeframe (seconds) -> protects the upstream provider.
    cache_ttl_m5: int = 20
    cache_ttl_m15: int = 30
    cache_ttl_h1: int = 90
    cache_ttl_h4: int = 240
    cache_ttl_d1: int = 900

    # --------------------------------------------------------------- scanner
    scanner_enabled: bool = True
    scanner_tick_seconds: int = 15
    # Watch every symbol in the watchlist even without a connected client.
    scanner_watch_all: bool = True
    scanner_default_timeframe: str = "M15"
    scanner_bars: int = 400

    # --------------------------------------------------------------- symbols
    watchlist: str = (
        "EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURGBP,EURJPY,GBPJPY"
    )

    # -------------------------------------------------------------- telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_enabled: bool = True  # notifier interface exists; config optional

    # ------------------------------------------------------------------- api
    cors_origins: str = "*"
    max_candles_per_request: int = 2000
    stream_heartbeat_seconds: int = 20

    # ----------------------------------------------------------- validators
    @model_validator(mode="after")
    def _resolve_database_path(self) -> "Settings":
        """Resolve a relative SQLite path against the project root.

        Without this the database file would be created relative to the process
        working directory, so ``python -m uvicorn`` from ``backend/`` and from the
        repository root would use two different files.
        """
        prefix = "sqlite+pysqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix):]
            if raw and raw != ":memory:" and not raw.startswith(("file:", "/")):
                absolute = (PROJECT_ROOT / raw).resolve()
                self.database_url = f"{prefix}{absolute}"
        return self

    # ----------------------------------------------------------- properties
    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        value = value.upper()
        if value not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return value

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def telegram_status(self) -> str:
        return "CONFIGURED" if self.telegram_configured else "NOT_CONFIGURED"

    def cache_ttl_for(self, timeframe: "Timeframe | str") -> int:
        from app.schemas.market import as_timeframe

        mapping = {
            "M5": self.cache_ttl_m5,
            "M15": self.cache_ttl_m15,
            "H1": self.cache_ttl_h1,
            "H4": self.cache_ttl_h4,
            "D1": self.cache_ttl_d1,
        }
        return mapping.get(as_timeframe(timeframe).value, self.cache_ttl_m15)

    def safe_snapshot(self) -> dict[str, object]:
        """Configuration state safe to log or to return through the API."""
        return {
            "app_env": self.app_env.value,
            "log_level": self.log_level,
            "market_data_provider": self.market_data_provider.value,
            "database_backend": "sqlite" if self.is_sqlite else "postgresql",
            "watchlist": self.symbol_list,
            "scanner_enabled": self.scanner_enabled,
            "scanner_tick_seconds": self.scanner_tick_seconds,
            "telegram": self.telegram_status,
            "telegram_bot_token_present": bool(self.telegram_bot_token),
            "telegram_chat_id_present": bool(self.telegram_chat_id),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
