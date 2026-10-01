"""Phase 8 - Telegram outbox, dispatcher and message tests.

Acceptance criteria checked here:

* the token comes from the environment only and never appears in a message, a
  queue row, a status payload or a log line (8.1);
* the message has the requested structure, ``WATCH`` uses 👀 and ``NO_TRADE``
  stays silent unless it is explicitly enabled (8.2, 8.3);
* the capture is attached when it exists, and its absence never blocks the text
  alert (8.4);
* the queue survives, the statuses are real (QUEUED / SENDING / SENT / FAILED /
  RETRYING), retries back off and give up after ``max_attempts`` (8.5);
* the scanner is never blocked and never waits for the network (8.6);
* the alert keeps the identity of the opportunity it comes from, end to end (8.7).

The Telegram API is never called in these tests: the notifier is replaced by a
double that records what it was asked to do.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.db.repository import TelegramOutboxRepository
from app.main import app as fastapi_app
from app.opportunities.models import Opportunity, OpportunityState, NoTradeReason
from app.schemas.events import EventType
from app.services.events import EventBus
from app.services.telegram import DeliveryResult, DeliveryStatus
from app.telegram.messages import build_caption, build_message, should_alert
from app.telegram.outbox import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RETRYING,
    STATUS_SENT,
    STATUS_SKIPPED,
    TelegramOutbox,
)
from app.telegram.params import MODE_DRY_RUN, MODE_NOT_CONFIGURED, MODE_REAL, TelegramParams
from tests import confluence_fixtures as cf_fx
from tests import opportunity_fixtures as op_fx

FAKE_TOKEN = "123456789:AAtest-token-that-must-never-appear-000"
FAKE_CHAT = "-1001234567890"


class RecordingNotifier:
    """Stands in for Telegram: records the calls, never touches the network."""

    def __init__(self, ok: bool = True, detail: str | None = None, token: str | None = FAKE_TOKEN) -> None:
        self.calls: list[tuple[str, str]] = []
        self.ok = ok
        self.detail = detail
        self._token = token
        self.message_id = 4242

    @property
    def configured(self) -> bool:
        return bool(self._token and FAKE_CHAT)

    def describe(self) -> dict:
        return {
            "status": "CONFIGURED" if self.configured else "NOT_CONFIGURED",
            "bot_token_present": bool(self._token),
            "bot_token_preview": "123456" if self._token else "NOT_SET",
            "chat_id_present": True,
            "chat_id_preview": "-1",
            "capabilities": ["send_message", "send_image"],
        }

    async def send_message(self, text: str, **kwargs) -> DeliveryResult:
        self.calls.append(("send_message", text))
        if self.ok:
            return DeliveryResult(DeliveryStatus.SENT, None, self.message_id)
        return DeliveryResult(DeliveryStatus.FAILED, self.detail or "HTTP 400")

    async def send_image(self, image, caption=None, **kwargs) -> DeliveryResult:
        self.calls.append(("send_image", str(image)))
        if self.ok:
            return DeliveryResult(DeliveryStatus.SENT, None, self.message_id)
        return DeliveryResult(DeliveryStatus.FAILED, self.detail or "HTTP 400")

    async def aclose(self) -> None:  # pragma: no cover - parity with the real notifier
        return None


@pytest.fixture
def market():
    return cf_fx.series(
        cf_fx.calm(70)
        + [
            cf_fx.BarSpec(open=0.0, high=0.6, low=-0.4, close=0.4),
            cf_fx.BarSpec(open=0.4, high=1.2, low=0.2, close=1.0),
            cf_fx.BarSpec(open=1.0, high=1.6, low=0.8, close=1.4),
        ]
    )


@pytest.fixture
def opportunity(market):
    """A real BUY observation, produced by the real Phase 6 engine."""
    from app.opportunities.engine import OpportunityEngine

    engine = OpportunityEngine(op_fx.params())
    result = engine.analyse(market, [op_fx.strong_group(market)])
    engine.commit(result)
    named = [item for item in result.opportunities if item.is_actionable_observation]
    assert named, "le scenario de reference doit produire une direction nommee"
    return named[0]


def make_outbox(tmp_path, *, mode: str = MODE_DRY_RUN, notifier=None, params: TelegramParams | None = None) -> TelegramOutbox:
    params = params or test_params()
    params.mode = mode
    return TelegramOutbox(
        params=params,
        repository=TelegramOutboxRepository(session_factory=_session_factory(tmp_path)),
        notifier=notifier or RecordingNotifier(),
        bus=EventBus(),
        captures=None,
        event_repository=None,
    )


def test_params(**overrides) -> "TelegramParams":
    """Parametres hermetiques : aucun test ne depend du .env de la machine.

    Le fichier .env de la racine contient la configuration de l'exploitant (mode
    DRY_RUN ou REAL, jeton...). Un test doit verifier le code, pas la
    configuration locale : on construit donc les parametres sur les valeurs par
    defaut, en ignorant explicitement tout fichier.
    """
    from app.telegram.params import TelegramParams as _Params

    return _Params(_env_file=None, **overrides)



class TestMessage:
    def test_the_message_has_the_requested_structure(self, opportunity):
        text = build_message(opportunity, test_params())
        lines = text.splitlines()
        assert lines[0] == "🚨 SMART MARKET VISION"
        assert lines[1] == f"{opportunity.symbol} · {opportunity.timeframe}"
        assert "🟢 BUY" in lines[2]
        assert any(line.startswith("Confluence ") for line in lines)
        assert any(line.startswith("État : ") for line in lines)
        assert any("STRUCTURE ✅" in line for line in lines)
        assert any(line.startswith("Prix : ") for line in lines)
        assert any(line.startswith("Validité : ") for line in lines)
        assert "aucune exécution automatique" in text.lower()

    def test_a_sell_uses_the_red_icon_and_a_watch_the_eyes(self, market, opportunity):
        params = test_params()
        assert "🟢" in build_message(opportunity, params)
        clone = opportunity.model_copy(update={"direction": "SELL", "state": OpportunityState.ACTIVE.value})
        assert "🔴 SELL" in build_message(clone, params)
        watching = opportunity.model_copy(update={"direction": "WATCH", "blocked_by": "CONFLUENCE_INSUFFISANTE"})
        text = build_message(watching, params)
        assert "👀" in text and "En attente : CONFLUENCE_INSUFFISANTE" in text

    def test_no_trade_is_silent_by_default_and_explains_itself_when_enabled(self, opportunity):
        refusal = opportunity.model_copy(
            update={"direction": "NO_TRADE", "no_trade_reason": NoTradeReason.CONTRADICTORY.value}
        )
        assert should_alert(refusal, test_params().message) is False
        enabled = test_params(message={"send_no_trade": True})
        enabled.message.send_no_trade = True
        text = build_message(refusal, enabled)
        assert "⛔" in text and NoTradeReason.CONTRADICTORY.value in text
        assert should_alert(refusal, enabled.message) is True
        assert should_alert(opportunity, test_params().message) is True

    def test_the_message_never_contains_an_order_vocabulary(self, opportunity):
        text = build_message(opportunity, test_params()).upper()
        for forbidden in ("STOP LOSS", "TAKE PROFIT", "LOT ", "BROKER", "PROBABIL", "GARANTI", "PERFORMANCE"):
            assert forbidden not in text

    def test_the_message_never_contains_the_token(self, opportunity):
        params = test_params()
        text = build_message(opportunity, params)
        caption = build_caption(opportunity, params)
        assert FAKE_TOKEN not in text and FAKE_TOKEN not in caption

    def test_a_long_message_is_truncated_to_the_limit(self, opportunity):
        params = test_params()
        params.message.max_chars = 200
        text = build_message(opportunity, params)
        assert len(text) <= 200


class TestModes:
    def test_absent_variables_give_not_configured(self, tmp_path):
        outbox = make_outbox(tmp_path, notifier=RecordingNotifier(token=None))
        assert outbox.mode == MODE_NOT_CONFIGURED
        assert outbox.status()["configured"] is False

    def test_configured_variables_default_to_dry_run(self, tmp_path):
        outbox = make_outbox(tmp_path)
        assert outbox.mode == MODE_DRY_RUN

    def test_real_requires_both_the_variables_and_the_explicit_mode(self, tmp_path):
        outbox = make_outbox(tmp_path, mode=MODE_REAL)
        assert outbox.mode == MODE_REAL
        absent = make_outbox(tmp_path, mode=MODE_REAL, notifier=RecordingNotifier(token=None))
        assert absent.mode == MODE_NOT_CONFIGURED, "REAL ne peut pas s'inventer sans variables"

    def test_the_mode_comes_from_the_environment_not_from_the_api(self, tmp_path):
        params = test_params()
        applied = params.apply_overrides({"mode": {"mode": "REAL"}, "message": {"title": "X"}})
        assert any("ignored:mode" in line for line in applied)
        # l'API ne peut pas changer le mode : il vient de la configuration.
        # test_params() ignore tout fichier, la valeur est donc deterministe.
        assert params.mode.upper() == MODE_DRY_RUN
        assert params.apply_overrides({"mode": {}}) == ["ignored:mode (seul .env decide du mode)"]
        assert params.message.title == "X"


class TestOutbox:
    def test_an_alert_is_queued_with_its_identity(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path)
        assert outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED") is True
        rows = outbox.history(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == STATUS_QUEUED
        assert row["opportunity_id"] == opportunity.id, "l'alerte garde l'identite de l'opportunite"
        assert row["alert_id"].startswith("al_")
        assert row["symbol"] == opportunity.symbol and row["timeframe"] == opportunity.timeframe
        assert row["message"].startswith("🚨")
        assert row["mode"] == MODE_DRY_RUN

    def test_the_same_alert_is_never_queued_twice(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path)
        assert outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED") is True
        assert outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED") is False
        assert outbox.duplicates == 1
        assert len(outbox.history(limit=10)) == 1

    def test_a_no_trade_is_skipped_without_a_row(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path)
        refusal = opportunity.model_copy(update={"direction": "NO_TRADE", "no_trade_reason": "X"})
        assert outbox.enqueue_opportunity(refusal, "OPPORTUNITY_CREATED") is False
        assert outbox.skipped == 1 and outbox.history(limit=10) == []

    def test_the_token_never_reaches_the_queue(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path)
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        row = outbox.history(limit=1)[0]
        dump = str(row)
        assert FAKE_TOKEN not in dump
        assert outbox.status()["notifier"]["bot_token_preview"] != FAKE_TOKEN

    def test_the_scanner_side_never_calls_the_network(self, tmp_path, opportunity):
        notifier = RecordingNotifier()
        outbox = make_outbox(tmp_path, notifier=notifier)
        for index in range(25):
            clone = opportunity.model_copy(
                update={"id": f"{opportunity.id}_{index}", "alert_key": f"EURUSD|M15|BUY|{index}"}
            )
            outbox.enqueue_opportunity(clone, "OPPORTUNITY_CREATED")
        assert notifier.calls == [], "mettre en file n'appelle jamais Telegram"
        assert len(outbox.history(limit=50)) == 25


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_dry_run_marks_the_alert_sent_without_any_call(self, tmp_path, opportunity):
        notifier = RecordingNotifier()
        outbox = make_outbox(tmp_path, notifier=notifier)
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")

        handled = await outbox.dispatch_once()
        assert handled == 1
        assert notifier.calls == [], "DRY_RUN ne touche pas le reseau"
        row = outbox.history(limit=1)[0]
        assert row["status"] == STATUS_SENT and row["mode"] == MODE_DRY_RUN
        assert row["sent_at"] is not None
        published = [event for event in outbox.bus.history(limit=20) if event.event_type is EventType.ALERT_SENT]
        assert published and published[-1].metadata["alert_id"] == row["id"]
        assert published[-1].metadata["trading_signal"] is False

    @pytest.mark.asyncio
    async def test_not_configured_keeps_the_alert_queued(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path, notifier=RecordingNotifier(token=None))
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        await outbox.dispatch_once()

        row = outbox.history(limit=1)[0]
        assert row["status"] == STATUS_QUEUED, "sans variables, rien n'est envoye et rien n'est perdu"
        assert "NOT_CONFIGURED" in (row["last_error"] or "")
        assert row["attempts"] == 0

    @pytest.mark.asyncio
    async def test_a_failure_is_retried_with_a_backoff_then_gives_up(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path, mode=MODE_REAL, notifier=RecordingNotifier(ok=False, detail="HTTP 500"))
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")

        await outbox.dispatch_once()
        row = outbox.history(limit=1)[0]
        assert row["status"] == STATUS_RETRYING and row["attempts"] == 1, "la tentative est enregistree"
        assert row["last_error"] == "HTTP 500"
        assert row["next_attempt_at"] is not None, "une nouvelle tentative est planifiee"

        # the row is not due yet: the dispatcher leaves it alone
        assert await outbox.dispatch_once() == 0

        # it becomes due, and after max_attempts the alert is definitively failed
        outbox.params.delivery.max_attempts = 1
        outbox.repository.mark(row["id"], next_attempt_at=datetime.now(tz=timezone.utc) - timedelta(seconds=1))
        await outbox.dispatch_once()
        final = outbox.history(limit=1)[0]
        assert final["status"] == STATUS_FAILED
        assert outbox.failed == 1
        failed_events = [e for e in outbox.bus.history(limit=20) if e.event_type is EventType.ALERT_FAILED]
        assert failed_events, "un echec definitif est publie"
        assert FAKE_TOKEN not in str(final)

    @pytest.mark.asyncio
    async def test_the_backoff_grows_with_the_attempts(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path, mode=MODE_REAL, notifier=RecordingNotifier(ok=False))
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        deltas: list[float] = []
        for _ in range(3):
            row = outbox.history(limit=1)[0]
            outbox.repository.mark(row["id"], next_attempt_at=datetime.now(tz=timezone.utc) - timedelta(seconds=1))
            await outbox.dispatch_once()
            current = outbox.history(limit=1)[0]
            if current["next_attempt_at"]:
                due = datetime.fromisoformat(current["next_attempt_at"].replace("Z", "+00:00"))
                deltas.append((due - datetime.now(tz=timezone.utc)).total_seconds())
        assert len(deltas) >= 2
        assert deltas[1] > deltas[0], "le delai augmente (backoff)"

    @pytest.mark.asyncio
    async def test_a_real_send_attaches_the_capture_when_it_exists(self, tmp_path, opportunity):
        class Captures:
            def __init__(self, path):
                self.path = path

            def history(self, limit=1, opportunity_id=None):
                return [{"id": "cap_1", "path": str(self.path), "telegram_path": str(self.path)}]

        image = tmp_path / "capture.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)

        notifier = RecordingNotifier()
        params = test_params()
        params.mode = MODE_REAL
        outbox = TelegramOutbox(
            params=params,
            repository=TelegramOutboxRepository(session_factory=_session_factory(tmp_path)),
            notifier=notifier,
            bus=EventBus(),
            captures=Captures(image),
        )
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        await outbox.dispatch_once()

        assert notifier.calls and notifier.calls[0][0] == "send_image"
        assert notifier.calls[0][1] == str(image), "c'est bien le PNG de la capture qui part"
        row = outbox.history(limit=1)[0]
        assert row["status"] == STATUS_SENT and row["capture_id"] == "cap_1"
        assert row["provider_message_id"] == 4242

    @pytest.mark.asyncio
    async def test_a_missing_capture_never_blocks_the_text_alert(self, tmp_path, opportunity):
        notifier = RecordingNotifier()
        params = test_params()
        params.mode = MODE_REAL
        params.delivery.capture_wait_seconds = 0.0
        outbox = TelegramOutbox(
            params=params,
            repository=TelegramOutboxRepository(session_factory=_session_factory(tmp_path)),
            notifier=notifier,
            bus=EventBus(),
            captures=None,
        )
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        await outbox.dispatch_once()
        assert notifier.calls and notifier.calls[0][0] == "send_message"
        assert outbox.history(limit=1)[0]["status"] == STATUS_SENT

    @pytest.mark.asyncio
    async def test_the_dispatcher_loop_is_a_separate_task(self, tmp_path, opportunity):
        outbox = make_outbox(tmp_path)
        outbox.params.delivery.poll_seconds = 0.05
        await outbox.start()
        assert outbox.status()["dispatcher"]["running"] is True
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        for _ in range(60):
            if outbox.history(limit=1) and outbox.history(limit=1)[0]["status"] == STATUS_SENT:
                break
            await __import__("asyncio").sleep(0.05)
        await outbox.stop()
        assert outbox.history(limit=1)[0]["status"] == STATUS_SENT
        assert outbox.status()["dispatcher"]["running"] is False


class TestEndToEndIdentity:
    @pytest.mark.asyncio
    async def test_the_alert_keeps_the_chain_identity(self, tmp_path, market, opportunity):
        """OHLC -> engines -> confluence -> opportunity -> outbox: same identity."""
        outbox = make_outbox(tmp_path)
        outbox.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        row = outbox.history(limit=1)[0]
        assert row["opportunity_id"] == opportunity.id
        assert opportunity.confluence_id in row["message"] or opportunity.confluence_id is None
        assert opportunity.confluence_id and opportunity.confluence_id.startswith("cf_")
        await outbox.dispatch_once()
        assert outbox.history(limit=1)[0]["status"] == STATUS_SENT


class TestApi:
    @pytest.fixture
    def client(self, tmp_path):
        container = Container.build()
        notifier = RecordingNotifier()
        container.telegram = make_outbox(tmp_path, notifier=notifier)
        container.opportunities.outbox = container.telegram
        fastapi_app.state.container = container
        with TestClient(fastapi_app) as test_client:
            yield test_client, container, notifier

    def test_the_status_exposes_the_queue_and_hides_the_token(self, client):
        test_client, _, _ = client
        payload = test_client.get("/api/telegram/status").json()
        assert payload["mode"] == MODE_DRY_RUN
        assert payload["queue"] == {"queued": 0, "sending": 0, "retrying": 0, "sent": 0, "failed": 0, "skipped": 0}
        assert isinstance(payload["dispatcher"]["running"], bool), "l'etat du dispatcher est explicite"
        assert payload["dispatcher"]["sent"] == 0
        assert FAKE_TOKEN not in str(payload)

    def test_the_history_endpoint_lists_the_real_alerts(self, client, opportunity):
        test_client, container, _ = client
        container.telegram.enqueue_opportunity(opportunity, "OPPORTUNITY_CREATED")
        body = test_client.get("/api/telegram/history").json()
        assert body["count"] == 1
        assert body["alerts"][0]["opportunity_id"] == opportunity.id
        assert body["counts"][STATUS_QUEUED] == 1
        assert body["trading_signal"] is False
        assert FAKE_TOKEN not in str(body)

    def test_params_are_visible_and_adjustable_but_not_the_mode(self, client):
        test_client, container, _ = client
        params = test_client.get("/api/telegram/params").json()
        assert params["mode"] == MODE_DRY_RUN
        assert params["params"]["message"]["send_no_trade"] is False

        response = test_client.patch(
            "/api/telegram/params", json={"overrides": {"delivery": {"max_attempts": 3}}}
        )
        assert response.status_code == 200
        assert "delivery.max_attempts=3" in response.json()["applied"]
        assert container.telegram.params.delivery.max_attempts == 3

    def test_the_test_route_goes_through_the_queue(self, client):
        test_client, container, notifier = client
        payload = test_client.post("/api/telegram/test").json()
        assert payload["status"] == "QUEUED" and payload["queued"] is True
        assert notifier.calls == [], "l'appel HTTP ne declenche aucun envoi : le dispatcher s'en charge"
        assert container.telegram.history(limit=5)


def _session_factory(tmp_path):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path/'telegram.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return scope

class TestEnvFileWiring:
    """Le .env de la RACINE doit etre lu (bug corrige : chemin relatif)."""

    def test_env_file_is_the_project_root(self) -> None:
        from pathlib import Path

        from app.config import PROJECT_ROOT
        from app.telegram.params import TelegramParams

        declared = TelegramParams.model_config.get("env_file")
        paths = [declared] if isinstance(declared, str) else list(declared or [])
        resolved = {Path(item).resolve() for item in paths}
        assert (PROJECT_ROOT / ".env").resolve() in resolved, resolved

    def test_mode_is_read_from_an_env_file(self, tmp_path) -> None:
        from app.telegram.params import TelegramParams

        env = tmp_path / ".env"
        env.write_text("TELEGRAM_MODE=REAL\nTELEGRAM_ENABLED=true\n", encoding="utf-8")
        params = TelegramParams(_env_file=env)
        assert params.mode.upper() == "REAL"
        assert params.effective_mode(True) == "REAL"
        assert params.effective_mode(False) == "NOT_CONFIGURED"

    def test_a_file_saying_real_never_overrides_missing_variables(self, tmp_path) -> None:
        from app.telegram.params import TelegramParams

        env = tmp_path / ".env"
        env.write_text("TELEGRAM_MODE=REAL\n", encoding="utf-8")
        params = TelegramParams(_env_file=env)
        # sans jeton ni chat_id, REAL est refuse : le mode retombe sur NOT_CONFIGURED
        assert params.effective_mode(False) == "NOT_CONFIGURED"


class TestOperatorTestAlert:
    """Un clic sur « tester » doit produire un message, pas etre avale."""

    def test_a_second_click_in_the_same_second_is_deduplicated(self, tmp_path) -> None:
        """Un double-clic ne doit pas produire deux messages (anti-spam)."""
        outbox = make_outbox(tmp_path)
        assert outbox.enqueue_test_alert() is True
        assert outbox.enqueue_test_alert() is False
        assert len(outbox.history(limit=10)) == 1

    def test_a_later_click_sends_a_new_message(self, tmp_path, monkeypatch) -> None:
        """Un test demande plus tard doit repartir : sinon le bouton ne repond plus.

        C'est le defaut corrige : l'identite etait figee, donc tout test ulterieur
        repondait ALREADY_QUEUED et l'operateur ne recevait plus rien.
        """
        from datetime import datetime, timedelta, timezone

        import app.telegram.outbox as outbox_module

        real_datetime = datetime
        moment = {"now": real_datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)}

        class FrozenDatetime(real_datetime):  # type: ignore[misc, valid-type]
            @classmethod
            def now(cls, tz=None):  # noqa: D102 - clock controlled by the test
                return moment["now"]

        monkeypatch.setattr(outbox_module, "datetime", FrozenDatetime)

        factory = _session_factory(tmp_path)
        outbox = TelegramOutbox(
            params=test_params(),
            repository=TelegramOutboxRepository(session_factory=factory),
            notifier=RecordingNotifier(),
            bus=EventBus(),
        )
        assert outbox.enqueue_test_alert() is True
        assert outbox.enqueue_test_alert() is False, "meme seconde : deduplique"
        moment["now"] = moment["now"] + timedelta(seconds=30)
        assert outbox.enqueue_test_alert() is True, "plus tard : un nouveau message part"
        assert len(outbox.history(limit=10)) == 2

    def test_the_alert_carries_the_test_identity(self, tmp_path) -> None:
        outbox = make_outbox(tmp_path)
        outbox.enqueue_test_alert()
        row = outbox.history(limit=1)[0]
        assert row["event_type"] == "TELEGRAM_TEST"
        assert row["symbol"] == "EURUSD"
        assert "op_test" in (row["opportunity_id"] or "")
        # aucun ordre, aucune execution : l'alerte est informative
        assert outbox.status()["mode"] in ("NOT_CONFIGURED", "DRY_RUN", "REAL")
