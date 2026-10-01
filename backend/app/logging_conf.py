"""Logging setup with secret redaction.

Any configured secret value (Telegram token, chat id, database password) that
happens to travel through a log record is replaced by ``***REDACTED***``.
Token-shaped strings are also redacted even when they are not in the settings,
which protects future providers.
"""

from __future__ import annotations

import logging
import re
import sys

from app.config import settings

REDACTED = "***REDACTED***"

# Telegram bot token shape: <bot_id>:<35ish chars>
TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
# user:password@host inside a connection URL
URL_CREDENTIALS = re.compile(r"(?<=://)([^:/@\s]+):([^@/\s]+)(?=@)")


class RedactionFilter(logging.Filter):
    """Scrub secrets from log messages and arguments."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 6]

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret and secret in text:
                text = text.replace(secret, REDACTED)
        text = TOKEN_PATTERN.sub(REDACTED, text)
        text = URL_CREDENTIALS.sub(r"\1:" + REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        scrubbed = self._scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def _secret_values() -> list[str]:
    values = [settings.telegram_bot_token, settings.telegram_chat_id]
    return [v for v in values if v]


def setup_logging(level: str | None = None) -> None:
    """Idempotent root logger configuration."""
    root = logging.getLogger()
    target_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)

    if getattr(root, "_smv_configured", False):
        root.setLevel(target_level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(RedactionFilter(_secret_values()))
    root.handlers = [handler]
    root.setLevel(target_level)
    root._smv_configured = True  # type: ignore[attr-defined]

    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(target_level, logging.WARNING))


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def mask_secret(value: str | None, keep: int = 4) -> str:
    """Return a mask safe for logs / API payloads."""
    if not value:
        return "NOT_SET"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * 6}"
