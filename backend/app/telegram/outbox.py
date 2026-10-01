"""Telegram outbox + dispatcher (Phase 8).

Architecture, exactly as required::

    Opportunity ──► TelegramOutbox (durable queue in SQLite)
                        │           never blocks the scanner
                        ▼
                  Dispatcher (separate asyncio task)
                        │  QUEUED → SENDING → SENT
                        │           ↘ FAILED → RETRYING → … (backoff)
                        ▼
                  TelegramNotifier ──► Telegram Bot API

Guarantees:

* the scanner only ever calls ``enqueue_*``: an insert in SQLite and nothing else;
* the dispatcher is the only component that talks to the network, in its own task;
* one alert per (opportunity, event, direction) thanks to a stable ``alert_id``:
  a restart cannot send the same alert twice, because the row already exists;
* every status transition is persisted, so the history is real and auditable;
* the token never appears in a row: only the message text and the file path do.

``DRY_RUN`` marks the alert as sent with ``mode=DRY_RUN`` and a marker in the
message, without any network call. ``NOT_CONFIGURED`` keeps the alerts queued and
says so in the status endpoint. Real delivery happens only when both variables
exist and ``TELEGRAM_MODE=REAL``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.repository import TelegramOutboxRepository
from app.logging_conf import get_logger
from app.opportunities.engine import alert_id
from app.opportunities.models import Opportunity
from app.schemas.events import EventType, MarketEvent
from app.services.events import EventBus, event_bus
from app.services.telegram import DeliveryStatus, TelegramNotifier
from app.telegram.messages import build_caption, build_message, should_alert
from app.telegram.params import MODE_DRY_RUN, MODE_NOT_CONFIGURED, MODE_REAL, TelegramParams
from app.telegram.params import params as default_params

logger = get_logger(__name__)

STATUS_QUEUED = "QUEUED"
STATUS_SENDING = "SENDING"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"
STATUS_RETRYING = "RETRYING"
STATUS_SKIPPED = "SKIPPED"


class TelegramOutbox:
    """Durable queue between the engines and Telegram."""

    def __init__(
        self,
        params: TelegramParams | None = None,
        repository: TelegramOutboxRepository | None = None,
        notifier: TelegramNotifier | None = None,
        bus: EventBus | None = None,
        captures=None,
        event_repository=None,
    ) -> None:
        self.params = params or default_params
        self.repository = repository or TelegramOutboxRepository()
        self.notifier = notifier or TelegramNotifier()
        self.bus = bus or event_bus
        self.captures = captures
        self.events_repo = event_repository
        self._task: asyncio.Task | None = None
        self.enqueued = 0
        self.duplicates = 0
        self.skipped = 0
        self.sent = 0
        self.failed = 0
        self.last_error: str | None = None
        self.last_sent_at: datetime | None = None

    # --------------------------------------------------------------- status
    @property
    def configured(self) -> bool:
        return self.notifier.configured

    @property
    def mode(self) -> str:
        return self.params.effective_mode(self.configured)

    def status(self) -> dict:
        """Secret-free status for the API and the dashboard."""
        return {
            "mode": self.mode,
            "enabled": self.params.enabled,
            "configured": self.configured,
            "notifier": self.notifier.describe(),
            "queue": {
                "queued": _queued(self.repository.count_by_status),
                "sending": _status_count(self.repository.count_by_status, "SENDING"),
                "retrying": _status_count(self.repository.count_by_status, "RETRYING"),
                "sent": _status_count(self.repository.count_by_status, "SENT"),
                "failed": _status_count(self.repository.count_by_status, "FAILED"),
                "skipped": _status_count(self.repository.count_by_status, "SKIPPED"),
            },
            "dispatcher": {
                "running": bool(self._task and not self._task.done()),
                "enqueued": self.enqueued,
                "duplicates_ignored": self.duplicates,
                "skipped": self.skipped,
                "sent": self.sent,
                "failed": self.failed,
                "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
                "last_error": self.last_error,
            },
            "note": (
                "DRY_RUN (defaut) : aucun envoi reseau, l'alerte est marquee comme envoyee en simulation. "
                "REAL seulement si TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID existent ET TELEGRAM_MODE=REAL."
            ),
        }

    # -------------------------------------------------------------- enqueue
    def enqueue_opportunity(self, opportunity: Opportunity, event_type: str) -> bool:
        """Queue one alert. Returns False when it is a duplicate or a silent refusal."""
        if not should_alert(opportunity, self.params.message):
            self.skipped += 1
            logger.info(
                "Telegram: %s %s %s non alerte (NO_TRADE silencieux par configuration)",
                opportunity.symbol,
                opportunity.timeframe,
                opportunity.direction,
            )
            return False
        identifier = alert_id(f"{opportunity.alert_key or opportunity.id}|{event_type}")
        entry = {
            "id": identifier,
            "alert_id": identifier,
            "opportunity_id": opportunity.id,
            "capture_id": None,
            "symbol": opportunity.symbol,
            "timeframe": opportunity.timeframe,
            "event_type": event_type,
            "message": build_message(opportunity, self.params),
            "caption": build_caption(opportunity, self.params),
            "status": STATUS_QUEUED,
            "mode": self.mode,
            "attempts": 0,
            "max_attempts": self.params.delivery.max_attempts,
            "created_at": datetime.now(tz=timezone.utc),
            "next_attempt_at": None,
        }
        try:
            created = self.repository.enqueue(entry)
        except Exception as exc:
            self.last_error = f"enqueue: {type(exc).__name__} - {exc}"
            logger.error("Telegram outbox enqueue failed: %s", self.last_error)
            return False
        if not created:
            self.duplicates += 1
            logger.debug("Telegram outbox: %s deja en file", identifier)
            return False
        self.enqueued += 1
        logger.info(
            "Telegram outbox: %s %s %s queued as %s",
            opportunity.symbol,
            opportunity.timeframe,
            opportunity.direction,
            identifier,
        )
        return True

    def enqueue_test_alert(self) -> bool:
        """One operator-triggered test alert, queued through the very same path.

        L'identite est horodatee : un clic sur « tester » doit produire UN
        message. La deduplication protege contre deux alertes identiques d'une
        meme opportunite, elle ne doit pas avaler une demande explicite de
        l'operateur (elle le faisait : le second test repondait ALREADY_QUEUED).
        Deux clics dans la meme seconde restent dedupliques.
        """
        from app.opportunities.models import Opportunity, OpportunityState

        now = datetime.now(tz=timezone.utc)
        stamp = now.strftime("%Y%m%d%H%M%S")
        probe = Opportunity(
            id=f"op_test_{stamp}",
            dedup_key="op_test",
            symbol="EURUSD",
            timeframe="M15",
            direction="WATCH",
            state=OpportunityState.ACTIVE.value,
            score=0.0,
            max_score=10.0,
            reference_price=None,
            blocked_by="TEST_MANUEL",
            created_at=now,
            updated_at=now,
            alert_key=f"TEST|EURUSD|M15|{stamp}",
            note="Test de connexion declenche par l'operateur.",
        )
        return self.enqueue_opportunity(probe, "TELEGRAM_TEST")

    # ----------------------------------------------------------- dispatcher
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(
                "Telegram dispatcher started (mode=%s, poll=%ss)",
                self.mode,
                self.params.delivery.poll_seconds,
            )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # pragma: no cover - shutdown path
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self.dispatch_once()
            except Exception as exc:  # pragma: no cover - the loop must survive
                self.last_error = f"dispatcher: {type(exc).__name__} - {exc}"
                logger.exception("Telegram dispatcher error: %s", self.last_error)
            await asyncio.sleep(self.params.delivery.poll_seconds)

    async def dispatch_once(self) -> int:
        """Send the pending alerts of the moment. Returns how many were handled."""
        pending = self.repository.next_pending(limit=self.params.delivery.batch_size)
        handled = 0
        for entry in pending:
            try:
                await self._deliver(entry)
                handled += 1
            except Exception as exc:  # pragma: no cover - defensive
                self.last_error = f"{entry['id']}: {type(exc).__name__} - {exc}"
                logger.exception("Telegram delivery crashed for %s", entry.get("id"))
                self._mark_failure(entry, self.last_error, int(entry.get("attempts") or 0) + 1)
        return handled

    async def _deliver(self, entry: dict) -> None:
        identifier = entry["id"]
        attempt = int(entry.get("attempts") or 0) + 1
        self.repository.mark(identifier, status=STATUS_SENDING, attempts=attempt)
        mode = self.mode

        if mode == MODE_NOT_CONFIGURED:
            # Nothing is sent and nothing is lost: the alert waits in the queue.
            self.repository.mark(
                identifier,
                status=STATUS_QUEUED,
                attempts=attempt - 1,
                last_error="TELEGRAM_NOT_CONFIGURED: variables absentes, alerte conservee en file",
            )
            self.last_error = "NOT_CONFIGURED"
            return

        if mode == MODE_DRY_RUN:
            # the image is not sent, but the alert is still linked to the real capture
            # so the dashboard and the history show which chart it refers to.
            _, capture_id = await self._capture_path(entry)
            self.repository.mark(
                identifier,
                status=STATUS_SENT,
                mode=MODE_DRY_RUN,
                sent_at=datetime.now(tz=timezone.utc),
                capture_id=capture_id,
                last_error=None,
                provider_message_id=None,
            )
            self.sent += 1
            self.last_sent_at = datetime.now(tz=timezone.utc)
            self._publish(identifier, entry, EventType.ALERT_SENT, extra={"mode": MODE_DRY_RUN})
            logger.info("Telegram DRY_RUN: alerte %s simulee (aucun appel reseau)", identifier)
            return

        capture_path, capture_id = await self._capture_path(entry)
        if capture_path is not None:
            result = await self.notifier.send_image(
                capture_path, caption=entry.get("caption") or None, filename=Path(capture_path).name
            )
        else:
            result = await self.notifier.send_message(entry.get("message") or "")

        if result.ok:
            self.repository.mark(
                identifier,
                status=STATUS_SENT,
                mode=MODE_REAL,
                sent_at=datetime.now(tz=timezone.utc),
                provider_message_id=result.message_id,
                capture_id=capture_id,
                last_error=None,
            )
            self.sent += 1
            self.last_sent_at = datetime.now(tz=timezone.utc)
            self._publish(identifier, entry, EventType.ALERT_SENT, extra={"mode": MODE_REAL})
            return

        self._mark_failure(entry, result.detail or result.status.value, attempt)

    def _mark_failure(self, entry: dict, detail: str, attempt: int) -> None:
        """Persist the failure, the number of attempts really made and the next try."""
        identifier = entry["id"]
        # The row remembers the policy it was queued under; the runtime parameter can
        # only TIGHTEN it (an operator lowering max_attempts never loosens a pending row).
        max_attempts = min(
            int(entry.get("max_attempts") or self.params.delivery.max_attempts),
            int(self.params.delivery.max_attempts),
        )
        if attempt >= max_attempts:
            self.repository.mark(identifier, status=STATUS_FAILED, last_error=detail[:500])
            self.failed += 1
            self.last_error = detail
            self._publish(identifier, entry, EventType.ALERT_FAILED, extra={"detail": detail})
            logger.error("Telegram: alerte %s en echec definitif (tentative %s)", identifier, attempt)
            return
        delay = self.params.delivery.backoff_seconds * (
            self.params.delivery.backoff_factor ** max(0, attempt - 1)
        )
        self.repository.mark(
            identifier,
            status=STATUS_RETRYING,
            attempts=attempt,  # the real number of attempts is persisted, not replayed
            last_error=detail[:500],
            next_attempt_at=datetime.now(tz=timezone.utc) + timedelta(seconds=delay),
        )
        self.last_error = detail
        logger.warning(
            "Telegram: alerte %s en echec (tentative %s/%s), nouvelle tentative dans %ss",
            identifier,
            attempt,
            max_attempts,
            round(delay, 1),
        )

    async def _capture_path(self, entry: dict) -> tuple[str | None, str | None]:
        """The real capture of the alert, when Phase 7 has produced it.

        Returns ``(path, capture_id)``. A capture that is still being rendered is
        waited for at most ``capture_wait_seconds``: after that the alert goes out
        as text, because a missing image must never hold an alert hostage.
        """
        opportunity_id = entry.get("opportunity_id")
        if not opportunity_id or self.captures is None or not self.params.message.send_capture:
            return None, None
        deadline = datetime.now(tz=timezone.utc) + timedelta(seconds=self.params.delivery.capture_wait_seconds)
        while True:
            try:
                rows = self.captures.history(limit=1, opportunity_id=opportunity_id)
            except Exception as exc:  # pragma: no cover - the queue must survive a lookup error
                logger.error("Telegram: consultation des captures impossible: %s", exc)
                return None, None
            if rows:
                row = rows[0]
                path = row.get("telegram_path") or row.get("path")
                if path and Path(path).exists():
                    return path, row.get("id")
            if datetime.now(tz=timezone.utc) >= deadline:
                break
            await asyncio.sleep(0.3)
        logger.info("Telegram: aucune capture disponible pour %s, envoi du texte seul", opportunity_id)
        return None, None

    # --------------------------------------------------------------- events
    def _publish(self, identifier: str, entry: dict, event_type: EventType, extra: dict | None = None) -> None:
        metadata = {
            "alert_id": identifier,
            "opportunity_id": entry.get("opportunity_id"),
            "symbol": entry.get("symbol"),
            "timeframe": entry.get("timeframe"),
            "status": "SENT" if event_type is EventType.ALERT_SENT else "FAILED",
            "trading_signal": False,
        }
        metadata.update(extra or {})
        event = MarketEvent(
            event_type=event_type,
            symbol=entry.get("symbol"),
            timeframe=entry.get("timeframe"),
            metadata=metadata,
            source="TELEGRAM_OUTBOX",
        )
        try:
            self.bus.publish_nowait(event)
        except Exception as exc:  # pragma: no cover - in-process bus
            logger.error("Telegram: publication impossible: %s", exc)
        if self.events_repo is not None:
            try:
                self.events_repo.save(event)
            except Exception as exc:  # pragma: no cover - best effort
                logger.error("Telegram: evenement non persiste: %s", exc)

    # -------------------------------------------------------------- reading
    def history(self, limit: int = 50, status: str | None = None) -> list[dict]:
        return self.repository.history(limit=limit, status=status)

    def get(self, entry_id: str) -> dict | None:
        return self.repository.get(entry_id)


def _status_count(counts_function, status: str) -> int:
    """One status counter, read from the real grouped query (never invented)."""
    try:
        return int((counts_function() or {}).get(status, 0))
    except Exception:  # pragma: no cover - locked database
        return -1


def _queued(counts_function) -> int:
    return _status_count(counts_function, STATUS_QUEUED)
