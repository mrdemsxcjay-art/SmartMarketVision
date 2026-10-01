"""Telegram notifier interface (Phase 1: interface + optional delivery).

Design constraints:
* Telegram is OPTIONAL. Missing ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``
  simply yields ``TELEGRAM = NOT_CONFIGURED`` and the app keeps working.
* The bot token is never logged, never returned by the API and never sent to the
  frontend. Log lines carry the HTTP method/status only.
* Notifications are informational output of an observation tool: this service
  cannot place, modify or close any order.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx

from app.config import settings
from app.logging_conf import get_logger, mask_secret

logger = get_logger(__name__)

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096


class DeliveryStatus(str, Enum):
    SENT = "SENT"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


@dataclass
class DeliveryResult:
    status: DeliveryStatus
    detail: str | None = None
    message_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.status is DeliveryStatus.SENT

    def as_dict(self) -> dict:
        return {"status": self.status.value, "detail": self.detail, "message_id": self.message_id}


class TelegramNotifier:
    """Thin wrapper over the Telegram Bot API."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = bot_token if bot_token is not None else settings.telegram_bot_token
        self._chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
        self._enabled = settings.telegram_enabled if enabled is None else enabled
        self._client = client
        self._owns_client = client is None
        self.last_result: DeliveryResult | None = None

    # ------------------------------------------------------------- state
    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    @property
    def status(self) -> str:
        """Public, secret-free status string used by the API and the dashboard."""
        if not self._enabled:
            return "DISABLED"
        return "CONFIGURED" if self.configured else "NOT_CONFIGURED"

    def describe(self) -> dict:
        """Safe description: presence flags and masked identifiers only."""
        return {
            "status": self.status,
            "bot_token_present": bool(self._token),
            "bot_token_preview": mask_secret(self._token, keep=6) if self._token else "NOT_SET",
            "chat_id_present": bool(self._chat_id),
            "chat_id_preview": mask_secret(self._chat_id, keep=2) if self._chat_id else "NOT_SET",
            "capabilities": ["send_message", "send_image"],
        }

    # ------------------------------------------------------------ helpers
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _endpoint(self, method: str) -> str:
        # NOTE: the token lives in the URL path - that URL is never logged.
        return f"{API_BASE}/bot{self._token}/{method}"

    def _guard(self) -> DeliveryResult | None:
        if not self._enabled:
            return DeliveryResult(DeliveryStatus.DISABLED, "telegram notifier disabled")
        if not self.configured:
            return DeliveryResult(
                DeliveryStatus.NOT_CONFIGURED,
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are not both set",
            )
        return None

    # --------------------------------------------------------------- API
    async def send_message(self, text: str, *, parse_mode: str | None = None) -> DeliveryResult:
        """Send a text message. Returns NOT_CONFIGURED instead of raising."""
        guard = self._guard()
        if guard:
            self.last_result = guard
            logger.debug("Telegram send_message skipped: %s", guard.detail)
            return guard

        payload: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": text[:MAX_MESSAGE_LENGTH],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        result = await self._post("sendMessage", data=payload)
        self.last_result = result
        return result

    async def send_image(
        self,
        image: str | Path | bytes,
        caption: str | None = None,
        *,
        filename: str = "snapshot.png",
    ) -> DeliveryResult:
        """Send a chart snapshot. Accepts a path or raw bytes."""
        guard = self._guard()
        if guard:
            self.last_result = guard
            logger.debug("Telegram send_image skipped: %s", guard.detail)
            return guard

        data: dict[str, object] = {"chat_id": self._chat_id}
        if caption:
            data["caption"] = caption[:1024]

        if isinstance(image, bytes):
            files = {"photo": (filename, image, "image/png")}
            result = await self._post("sendPhoto", data=data, files=files)
        else:
            path = Path(image)
            if not path.exists():
                result = DeliveryResult(DeliveryStatus.FAILED, f"image not found: {path.name}")
                self.last_result = result
                logger.error("Telegram send_image: image not found (%s)", path.name)
                return result
            with path.open("rb") as handle:
                files = {"photo": (path.name, handle.read(), "image/png")}
            result = await self._post("sendPhoto", data=data, files=files)

        self.last_result = result
        return result

    async def _post(self, method: str, data: dict, files: dict | None = None) -> DeliveryResult:
        client = await self._get_client()
        try:
            response = await client.post(self._endpoint(method), data=data, files=files)
            if response.status_code >= 400:
                detail = f"HTTP {response.status_code}"
                try:  # the API explains the failure in the body (e.g. "chat not found")
                    body = response.json()
                    detail = str(body.get("description") or detail)
                except Exception:  # pragma: no cover - non JSON error page
                    pass
                logger.error("Telegram %s failed with HTTP %s", method, response.status_code)
                return DeliveryResult(DeliveryStatus.FAILED, detail)
            body = response.json()
            if not body.get("ok"):
                description = str(body.get("description", "unknown error"))
                logger.error("Telegram %s rejected: %s", method, description)
                return DeliveryResult(DeliveryStatus.FAILED, description)
            message_id = (body.get("result") or {}).get("message_id")
            logger.info("Telegram %s delivered (message_id=%s)", method, message_id)
            return DeliveryResult(DeliveryStatus.SENT, None, message_id)
        except httpx.HTTPError as exc:
            logger.error("Telegram %s transport error: %s", method, type(exc).__name__)
            return DeliveryResult(DeliveryStatus.FAILED, f"{type(exc).__name__}")
        finally:
            if self._owns_client and self._client is not None:
                pass  # keep the connection pool for the next notification


notifier = TelegramNotifier()
