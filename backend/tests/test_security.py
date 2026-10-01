"""Security tests: no secret leaks, no trading surface, safe error envelopes."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config import settings
from app.logging_conf import REDACTED, RedactionFilter, mask_secret
from app.services.telegram import DeliveryStatus, TelegramNotifier

FAKE_TOKEN = "123456789:AAFakeTokenForTestsOnly_0123456789abcd"
FAKE_CHAT = "987654321"


class TestLogRedaction:
    def test_telegram_token_is_redacted_from_log_records(self, caplog):
        logger = logging.getLogger("app.test.redaction")
        logger.addFilter(RedactionFilter([FAKE_TOKEN, FAKE_CHAT]))
        with caplog.at_level(logging.INFO):
            logger.info("calling https://api.telegram.org/bot%s/sendMessage", FAKE_TOKEN)
            logger.info("chat_id=%s", FAKE_CHAT)
        joined = " ".join(record.getMessage() for record in caplog.records)
        assert FAKE_TOKEN not in joined
        assert FAKE_CHAT not in joined
        assert REDACTED in joined

    def test_token_shaped_strings_are_redacted_even_when_unknown(self, caplog):
        logger = logging.getLogger("app.test.redaction2")
        logger.addFilter(RedactionFilter([]))
        with caplog.at_level(logging.INFO):
            logger.info("leak attempt %s", "123456789:AAF1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q")
        assert "AAF1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q" not in caplog.records[-1].getMessage()

    def test_credentials_inside_urls_are_redacted(self):
        filt = RedactionFilter([])
        record = logging.LogRecord(
            "x", logging.INFO, __file__, 1, "postgresql://user:s3cretpw@db:5432/app", None, None
        )
        filt.filter(record)
        assert "s3cretpw" not in record.getMessage()

    def test_mask_secret(self):
        assert mask_secret(None) == "NOT_SET"
        assert mask_secret("abcdef123456", keep=6).startswith("abcdef")
        assert "123456" not in mask_secret("abcdef123456", keep=6)
        assert mask_secret("abcdef123456").startswith("abcd")


class TestApiDoesNotLeakSecrets:
    def test_status_endpoint_has_no_secret(self, client):
        body = client.get("/api/status").text
        for forbidden in ("bot_token\"", "TELEGRAM_BOT_TOKEN", "AAFake"):
            assert forbidden not in body
        payload = json.loads(body)
        preview = payload["telegram"]["bot_token_preview"]
        # la regle est le MASQUAGE, pas l'absence : configure ou non, l'apercu ne
        # doit jamais contenir le jeton (et "NOT_SET" quand il n'y en a pas).
        assert preview == "NOT_SET" or preview.endswith("*" * 6)
        if settings.telegram_bot_token:
            assert settings.telegram_bot_token not in preview
        assert payload["config"]["telegram_bot_token_present"] is bool(settings.telegram_bot_token)

    def test_health_and_config_are_sanitised(self, client):
        for url in ("/api/health", "/api/ready", "/api/status"):
            text = client.get(url).text
            assert FAKE_TOKEN not in text
            assert settings.telegram_bot_token not in text if settings.telegram_bot_token else True

    def test_error_envelope_does_not_expose_internals(self, client, provider):
        from app.providers.errors import ProviderBadPayload

        provider.fail_with = ProviderBadPayload("internal detail with /home/user/path")
        response = client.get("/api/candles/EURUSD/M15?limit=50")
        assert response.status_code == 503
        assert response.json()["cause"] == "PROVIDER_BAD_PAYLOAD"


class TestTelegramNotifier:
    @pytest.mark.asyncio
    async def test_not_configured_is_a_soft_failure(self):
        # chaines vides explicites : le test ne doit JAMAIS retomber sur le jeton
        # reellement configure dans .env (il enverrait un vrai message).
        notifier = TelegramNotifier(bot_token="", chat_id="")
        result = await notifier.send_message("hello")
        assert result.status is DeliveryStatus.NOT_CONFIGURED
        assert result.ok is False
        assert notifier.status == "NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_send_message_posts_without_logging_the_token(self, caplog):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token=FAKE_TOKEN, chat_id=FAKE_CHAT, client=client)
        with caplog.at_level(logging.DEBUG):
            result = await notifier.send_message("phase 1 test")

        assert result.status is DeliveryStatus.SENT
        assert result.message_id == 42
        assert FAKE_TOKEN in captured["url"], "the token belongs in the URL path"
        assert FAKE_CHAT in captured["body"]
        logged = " ".join(record.getMessage() for record in caplog.records)
        assert FAKE_TOKEN not in logged, "the token must never reach the logs"
        assert notifier.describe()["bot_token_preview"].endswith("******")

    @pytest.mark.asyncio
    async def test_send_image_reports_a_missing_file(self):
        notifier = TelegramNotifier(bot_token=FAKE_TOKEN, chat_id=FAKE_CHAT)
        result = await notifier.send_image("/tmp/does-not-exist-smv.png")
        assert result.status is DeliveryStatus.FAILED
        assert "not found" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_http_error_is_reported_not_raised(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"ok": False, "description": "chat not found"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notifier = TelegramNotifier(bot_token=FAKE_TOKEN, chat_id=FAKE_CHAT, client=client)
        result = await notifier.send_message("x")
        assert result.status is DeliveryStatus.FAILED
        assert result.detail == "chat not found"


class TestNoTradingSurface:
    def _all_routes(self, app) -> set[str]:
        paths: set[str] = set()

        def walk(routes) -> None:
            for route in routes:
                path = getattr(route, "path", None)
                if path:
                    paths.add(path)
                nested = getattr(route, "routes", None)
                if nested:
                    walk(nested)

        walk(app.routes)
        return paths

    def test_no_order_or_execution_endpoint_exists(self):
        from app.main import app

        paths = self._all_routes(app)
        forbidden = ("order", "trade", "execute", "position", "broker", "account", "withdraw")
        assert not any(word in path.lower() for path in paths for word in forbidden)

    def test_no_http_method_other_than_get_post(self):
        from app.main import app

        methods: set[str] = set()

        def walk(routes) -> None:
            for route in routes:
                methods.update(getattr(route, "methods", set()) or set())
                nested = getattr(route, "routes", None)
                if nested:
                    walk(nested)

        walk(app.routes)
        assert methods <= {"GET", "POST", "HEAD", "OPTIONS"}

    def test_safety_block_is_part_of_the_status_payload(self, client):
        payload = client.get("/api/status").json()
        assert payload["safety"]["order_execution"] is False
        assert payload["safety"]["broker_connection"] is False
        assert payload["safety"]["position_management"] is False


class TestTestEnvironmentNeverReachesTelegram:
    """La configuration Telegram est neutralisee des que APP_ENV=test.

    Sans cette garantie, un test executé sur la machine de l'exploitant pouvait
    utiliser le jeton reel de son .env et envoyer un vrai message (cas observe).
    """

    def test_settings_ignore_the_operator_token_in_test_env(self):
        from app.config import AppEnv, settings

        assert settings.app_env is AppEnv.TEST, "la suite de tests pose APP_ENV=test"
        assert settings.telegram_bot_token is None
        assert settings.telegram_chat_id is None
        assert settings.telegram_status == "NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_default_notifier_cannot_send_anything_in_test_env(self):
        from app.services.telegram import TelegramNotifier

        notifier = TelegramNotifier()  # aucun argument : retombe sur la configuration
        assert notifier.configured is False
        result = await notifier.send_message("ce message ne doit jamais partir")
        assert result.status is DeliveryStatus.NOT_CONFIGURED
