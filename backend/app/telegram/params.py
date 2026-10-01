"""Centralised Telegram parameters (Phase 8).

Constraints carried over from the earlier phases and enforced here:

* the token lives in ``.env`` only (``TELEGRAM_BOT_TOKEN``), never in the code, the
  logs, the reports, the dashboard, the captures or an exception message;
* the mode is derived from the environment: ``NOT_CONFIGURED`` when the variables
  are missing, ``DRY_RUN`` when ``TELEGRAM_MODE=DRY_RUN`` (the default) and
  ``REAL`` only when the variables really exist AND ``TELEGRAM_MODE=REAL``;
* an alert is informative output of an observation tool. There is no order, no
  broker, no position anywhere in this module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR, PROJECT_ROOT

#: how the bot is allowed to behave
MODE_NOT_CONFIGURED = "NOT_CONFIGURED"
MODE_DRY_RUN = "DRY_RUN"
MODE_REAL = "REAL"


class TelegramMessageParams(BaseModel):
    """Content of the message (8.2)."""

    title: str = Field(default="SMART MARKET VISION")
    header_icon: str = Field(default="🚨")
    buy_icon: str = Field(default="🟢")
    sell_icon: str = Field(default="🔴")
    watch_icon: str = Field(default="👀")
    no_trade_icon: str = Field(default="⛔")
    send_no_trade: bool = Field(
        default=False,
        description="NO_TRADE stays silent unless this is explicitly enabled",
    )
    show_dimensions: bool = Field(default=True, description="STRUCTURE / LIQUIDITY / IMBALANCE / ...")
    show_levels: bool = Field(default=True)
    max_chars: int = Field(default=3800, ge=200, le=4096)
    caption_max_chars: int = Field(default=900, ge=100, le=1024)
    send_capture: bool = Field(default=True, description="attach the real chart capture")
    disclaimer: str = Field(
        default="⚠️ Observation uniquement — aucune exécution automatique, aucun ordre.",
    )


class TelegramDeliveryParams(BaseModel):
    """Queue and retry policy (8.5)."""

    poll_seconds: float = Field(default=1.5, ge=0.2, le=60.0)
    batch_size: int = Field(default=5, ge=1, le=50)
    max_attempts: int = Field(default=5, ge=1, le=20)
    backoff_seconds: float = Field(default=5.0, ge=0.5, le=600.0)
    backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    capture_wait_seconds: float = Field(
        default=6.0, ge=0.0, le=120.0, description="how long a dispatcher waits for the capture of an alert"
    )
    history_limit: int = Field(default=200, ge=10, le=2000)


class TelegramParams(BaseSettings):
    """Runtime parameters of the Telegram interface (``TELEGRAM_`` prefix)."""

    #: The .env of the PROJECT ROOT, given as an absolute path: a relative
    #: ``".env"`` is resolved against the current working directory, so the
    #: parameters silently ignored the file whenever the process was started
    #: from another directory (the mode stayed DRY_RUN while .env said REAL).
    #: Environment variables keep precedence over the file.
    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_",
        env_file=(PROJECT_ROOT / ".env", BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(default=True)
    mode: str = Field(default=MODE_DRY_RUN, description="DRY_RUN | REAL (REAL only if variables exist)")
    message: TelegramMessageParams = Field(default_factory=TelegramMessageParams)
    delivery: TelegramDeliveryParams = Field(default_factory=TelegramDeliveryParams)

    GROUPS: tuple[str, ...] = ("message", "delivery")

    def effective_mode(self, configured: bool) -> str:
        """The mode really used: env decides, never the wishful thinking of a caller."""
        if not self.enabled:
            return MODE_NOT_CONFIGURED
        if not configured:
            return MODE_NOT_CONFIGURED
        return MODE_REAL if self.mode.upper() == MODE_REAL else MODE_DRY_RUN

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.GROUPS:
            value = getattr(self, name, None)
            if isinstance(value, BaseModel):
                out[name] = value.model_dump()
        out["derived"] = {
            "mode_env": self.mode.upper(),
            "enabled": self.enabled,
            "note": (
                "REAL n'est utilise que si TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID existent "
                "ET que TELEGRAM_MODE=REAL. Sinon le mode est DRY_RUN, ou NOT_CONFIGURED "
                "si les variables sont absentes."
            ),
        }
        return out

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> list[str]:
        applied: list[str] = []
        for group, values in (overrides or {}).items():
            target = getattr(self, group, None)
            if group == "mode":
                applied.append("ignored:mode (seul .env decide du mode)")
                continue
            if not isinstance(target, BaseModel):
                applied.append(f"ignored:{group}")
                continue
            for key, value in (values or {}).items():
                if key not in type(target).model_fields:
                    applied.append(f"ignored:{group}.{key}")
                    continue
                setattr(target, key, value)
                applied.append(f"{group}.{key}={value}")
        return applied


params = TelegramParams()
