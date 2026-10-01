"""Event bus used by the scanner and the real-time stream.

Single process, asyncio-native: no broker, no extra infrastructure.
Subscribers (WebSocket connections) receive only real events produced from
real market data.
"""

from __future__ import annotations

import asyncio
from collections import deque

from app.logging_conf import get_logger
from app.schemas.events import EventType, MarketEvent

logger = get_logger(__name__)

QUEUE_MAXSIZE = 200


class EventBus:
    def __init__(self, history_size: int = 200) -> None:
        self._subscribers: dict[int, asyncio.Queue[MarketEvent]] = {}
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._history: deque[MarketEvent] = deque(maxlen=history_size)
        self._published_total = 0
        #: loop that owns the subscriber queues (set on first subscribe)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def subscribe(self) -> tuple[int, asyncio.Queue[MarketEvent]]:
        async with self._lock:
            queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
            subscriber_id = self._next_id
            self._next_id += 1
            self._subscribers[subscriber_id] = queue
            self._loop = asyncio.get_running_loop()
        logger.info("Stream subscriber connected (#%s, total=%s)", subscriber_id, len(self._subscribers))
        return subscriber_id, queue

    async def unsubscribe(self, subscriber_id: int) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)
            remaining = len(self._subscribers)
        logger.info("Stream subscriber disconnected (#%s, total=%s)", subscriber_id, remaining)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def published_total(self) -> int:
        return self._published_total

    def history(self, limit: int = 30) -> list[MarketEvent]:
        return list(self._history)[-limit:]

    def publish_nowait(self, event: MarketEvent) -> None:
        """Non-blocking publish, safe from any thread.

        asyncio queues belong to the loop that created them, so a publish coming
        from another thread (thread pool, test client, future worker) is handed
        back to the owning loop with ``call_soon_threadsafe``.
        """
        self._published_total += 1
        self._history.append(event)

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None
            if current is not loop:
                try:
                    loop.call_soon_threadsafe(self._deliver, event)
                except RuntimeError:  # pragma: no cover - loop closed meanwhile
                    logger.debug("Event loop closed, dropping event %s", event.id)
                return

        self._deliver(event)

    def _deliver(self, event: MarketEvent) -> None:
        for subscriber_id, queue in list(self._subscribers.items()):
            if queue.full():
                # Slow client: drop its oldest event instead of stalling the scanner.
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:  # pragma: no cover - race
                    pass
                logger.debug("Dropped one event for slow subscriber #%s", subscriber_id)
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - race
                logger.warning("Queue full for subscriber #%s", subscriber_id)

    async def publish(self, event: MarketEvent) -> None:
        self.publish_nowait(event)

    async def snapshot_event(self) -> MarketEvent:
        return MarketEvent(
            event_type=EventType.SYSTEM_STATUS,
            metadata={
                "subscribers": self.subscriber_count,
                "events_published": self._published_total,
            },
            source="EVENT_BUS",
        )

    def clear(self) -> None:
        """Test helper."""
        self._subscribers.clear()
        self._history.clear()
        self._published_total = 0


event_bus = EventBus()
