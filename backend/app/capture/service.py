"""Capture service (Phase 7) - real PNGs, deduplicated, out of the scanner path.

Flow::

    scanner tick ──► CaptureService.request(...)   (returns immediately)
                          │
                          ▼  asyncio.Queue
                     worker task ──► scene -> Pillow -> PNG + metadata

A capture is only ever produced from a real candle series and real detections: if
the series is empty, the service reports ``CAPTURE_FAILED_NO_DATA`` instead of
writing a placeholder image. Two identical readings produce one file (7.4): the
identity is derived from symbol + timeframe + bar time + observation + resolution,
and the digest is the real sha256 of the PNG.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from app.capture.models import CaptureMetadata, CaptureResult, CaptureScene
from app.capture.params import CaptureParams, Resolution
from app.capture.params import params as default_params
from app.capture.renderer import render_scene, save_png
from app.capture.scene import build_scene
from app.config import DEFAULT_DATA_DIR
from app.confluence.models import ConfluenceGroup
from app.db.repository import CaptureRepository, EventRepository
from app.logging_conf import get_logger
from app.opportunities.models import Opportunity
from app.schemas.events import EventType, MarketEvent, PatternDetection
from app.schemas.market import CandleSeries
from app.services.events import EventBus, event_bus

logger = get_logger(__name__)

ENGINE_NAME = "CAPTURE_ENGINE"
STATUS_READY = "CAPTURE_READY"
STATUS_FAILED = "CAPTURE_FAILED"
STATUS_NO_DATA = "CAPTURE_FAILED_NO_DATA"
STATUS_DISABLED = "CAPTURE_NOT_IMPLEMENTED"


def capture_id_for(symbol: str, timeframe: str, bar_time: int | None, opportunity_id: str | None) -> str:
    """Stable identity of a reading: the same reading is the same capture."""
    payload = f"{symbol}|{timeframe}|{bar_time or 0}|{opportunity_id or 'none'}"
    return "cap_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


class CaptureService:
    def __init__(
        self,
        params: CaptureParams | None = None,
        repository: CaptureRepository | None = None,
        bus: EventBus | None = None,
        event_repository: EventRepository | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.params = params or default_params
        self.repository = repository or CaptureRepository()
        self.bus = bus or event_bus
        self.events_repo = event_repository or EventRepository()
        self.output_dir = Path(output_dir) if output_dir else (
            Path(self.params.output_dir) if self.params.output_dir else DEFAULT_DATA_DIR / "captures"
        )

        self.rendered = 0
        self.reused = 0
        self.failed = 0
        self.dropped = 0
        self.last_render_ms: float | None = None
        self.last_capture_at: datetime | None = None
        self.errors: list[str] = []
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._worker: asyncio.Task | None = None

    # ----------------------------------------------------------- queue side
    def request(
        self,
        series: CandleSeries,
        *,
        detections: list[PatternDetection] | None = None,
        confluences: list[ConfluenceGroup] | None = None,
        opportunity: Opportunity | None = None,
        timeframe: str | None = None,
    ) -> str | None:
        """Queue a capture. Never blocks, never raises: the scanner keeps running."""
        if not self.params.enabled:
            return None
        opportunity_id = opportunity.id if opportunity else None
        bar_time = max((candle.time for candle in series.candles), default=None)
        identifier = capture_id_for(series.symbol, timeframe or series.timeframe.value, bar_time, opportunity_id)
        try:
            self._queue.put_nowait(
                {
                    "id": identifier,
                    "series": series,
                    "detections": list(detections or []),
                    "confluences": list(confluences or []),
                    "opportunity": opportunity,
                    "timeframe": timeframe or series.timeframe.value,
                }
            )
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("Capture queue full: request for %s dropped (scanner untouched)", identifier)
            return None
        return identifier

    def start_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_worker())
            logger.info("Capture worker started (queue=%s)", self._queue.qsize())

    async def stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None:
            return
        worker.cancel()
        try:
            await worker
        except (asyncio.CancelledError, Exception):  # pragma: no cover - shutdown
            pass

    async def _run_worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                # The renderer is CPU bound: it must never sit on the event loop
                # that serves the market stream.
                await asyncio.to_thread(self.capture_now, job["series"], **{
                    key: value for key, value in job.items() if key not in ("series", "id")
                })
            except Exception as exc:  # pragma: no cover - defensive
                self.failed += 1
                message = f"{job['id']}: {type(exc).__name__} - {exc}"
                logger.exception("Capture failed: %s", message)
                self.errors = ([message] + self.errors)[:10]
            finally:
                self._queue.task_done()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    # ----------------------------------------------------------- sync side
    def capture_now(
        self,
        series: CandleSeries,
        *,
        detections: list[PatternDetection] | None = None,
        confluences: list[ConfluenceGroup] | None = None,
        opportunity: Opportunity | None = None,
        timeframe: str | None = None,
        timestamp: datetime | None = None,
    ) -> CaptureResult:
        """Render synchronously. Returns the metadata of the (possibly reused) file."""
        if not self.params.enabled:
            return CaptureResult(status=STATUS_DISABLED, reason="capture desactivee par configuration")
        started = datetime.now(tz=timezone.utc)
        candle_count = sum(1 for candle in series.candles if candle.closed)
        if candle_count == 0:
            self.failed += 1
            return CaptureResult(
                status=STATUS_NO_DATA,
                reason="aucune bougie cloturee : capture non produite (jamais d'image inventee)",
            )

        scene = build_scene(
            series,
            timeframe=timeframe,
            detections=detections,
            confluences=confluences,
            opportunity=opportunity,
            params=self.params,
            timestamp=timestamp,
        )
        opportunity_id = opportunity.id if opportunity else None
        identifier = capture_id_for(scene.symbol, scene.timeframe, scene.candles[-1].time, opportunity_id)

        if self.params.dedup:
            existing = self._existing(identifier)
            if existing is not None:
                self.reused += 1
                return CaptureResult(
                    status=STATUS_READY,
                    metadata=self._metadata_from_row(existing),
                    scene=scene,
                    reused=True,
                )

        try:
            phone = self.params.resolution("phone")
            telegram = self.params.resolution("telegram")
            image = render_scene(scene, self.params, phone)
            path = self._path_for(scene, identifier, phone)
            size = save_png(image, path)
            telegram_path = self._path_for(scene, identifier, telegram)
            save_png(render_scene(scene, self.params, telegram), telegram_path)
        except Exception as exc:
            self.failed += 1
            message = f"{identifier}: {type(exc).__name__} - {exc}"
            logger.exception("Capture rendering failed: %s", message)
            self.errors = ([message] + self.errors)[:10]
            return CaptureResult(status=STATUS_FAILED, reason=message, scene=scene)

        digest = _sha256(path)
        metadata = CaptureMetadata(
            capture_id=identifier,
            opportunity_id=opportunity_id,
            confluence_id=(opportunity.confluence_id if opportunity else (confluences[0].id if confluences else None)),
            symbol=scene.symbol,
            timeframe=scene.timeframe,
            timestamp=scene.timestamp,
            path=str(path),
            hash=digest,
            width=phone.width,
            height=phone.height,
            resolution=phone.name,
            bytes=size,
            overlay_count=len(scene.overlays),
            tier=telegram.name,
            dedup_key=identifier,
        )
        self._persist(metadata, scene, telegram_path)
        self.rendered += 1
        self.last_capture_at = started
        self.last_render_ms = round((datetime.now(tz=timezone.utc) - started).total_seconds() * 1000, 2)
        self._publish(metadata, scene)
        logger.info(
            "Capture %s %s %s: %sx%s, %s bytes, %s overlays, %sms",
            scene.symbol,
            scene.timeframe,
            identifier,
            phone.width,
            phone.height,
            size,
            len(scene.overlays),
            self.last_render_ms,
        )
        return CaptureResult(status=STATUS_READY, metadata=metadata, scene=scene)

    # -------------------------------------------------------------- storage
    def _path_for(self, scene: CaptureScene, identifier: str, resolution: Resolution) -> Path:
        stamp = datetime.fromtimestamp(scene.candles[-1].time, tz=timezone.utc).strftime("%Y%m%dT%H%M")
        name = f"{scene.symbol}_{scene.timeframe}_{stamp}_{identifier}_{resolution.name}.png"
        return self.output_dir / name

    def _existing(self, identifier: str) -> dict | None:
        try:
            row = self.repository.get(identifier)
        except Exception as exc:  # pragma: no cover - locked database
            logger.error("Capture lookup failed for %s: %s", identifier, exc)
            return None
        if not row:
            return None
        path = Path(row.get("path") or "")
        if not path.exists():
            return None
        return row

    def _persist(self, metadata: CaptureMetadata, scene: CaptureScene, telegram_path: Path) -> None:
        row = {
            "id": metadata.capture_id,
            "opportunity_id": metadata.opportunity_id,
            "symbol": metadata.symbol,
            "timeframe": metadata.timeframe,
            "timestamp": metadata.timestamp,
            "bar_time": scene.candles[-1].time if scene.candles else None,
            "path": metadata.path,
            "telegram_path": str(telegram_path),
            "digest": metadata.hash,
            "width": metadata.width,
            "height": metadata.height,
            "size_bytes": metadata.bytes,
            "candles_drawn": len(scene.candles),
            "overlays_json": _overlays_json(scene),
            "state": "RENDERED",
        }
        try:
            self.repository.save(row)
        except Exception as exc:
            logger.error("Could not persist capture %s: %s", metadata.capture_id, exc)
            self.errors = ([f"persistence: {exc}"] + self.errors)[:10]

    def _publish(self, metadata: CaptureMetadata, scene: CaptureScene) -> None:
        payload = metadata.as_dict()
        payload.update(
            {
                "overlays": [
                    {"kind": item.kind.value, "label": item.label, "priority": item.priority, "source": item.source}
                    for item in scene.overlays
                ],
                "headline": scene.headline,
                "notes": scene.notes,
                "trading_signal": False,
            }
        )
        event = MarketEvent(
            event_type=EventType.CAPTURE_READY,
            symbol=metadata.symbol,
            timeframe=metadata.timeframe,
            price=scene.price,
            metadata=payload,
            source=ENGINE_NAME,
        )
        try:
            self.bus.publish_nowait(event)
        except Exception as exc:  # pragma: no cover - bus is in-process
            logger.error("Could not publish capture event: %s", exc)
        try:
            self.events_repo.save(event)
        except Exception as exc:  # pragma: no cover - best effort
            logger.error("Could not persist capture event: %s", exc)

    # -------------------------------------------------------------- reading
    def get(self, capture_id: str) -> dict | None:
        return self.repository.get(capture_id)

    def history(self, limit: int = 50, symbol: str | None = None, opportunity_id: str | None = None) -> list[dict]:
        return self.repository.history(limit=limit, symbol=symbol, opportunity_id=opportunity_id)

    def stats(self) -> dict:
        return {
            "engine": ENGINE_NAME,
            "enabled": self.params.enabled,
            "rendered": self.rendered,
            "reused": self.reused,
            "failed": self.failed,
            "dropped": self.dropped,
            "queue": self.queue_size,
            "worker_running": bool(self._worker and not self._worker.done()),
            "last_render_ms": self.last_render_ms,
            "last_capture_at": self.last_capture_at.isoformat() if self.last_capture_at else None,
            "persisted": _safe(self.repository.count),
            "output_dir": str(self.output_dir),
            "errors": self.errors[:5],
        }

    def describe(self) -> dict:
        return {
            "implemented": True,
            "enabled": self.params.enabled,
            "status": STATUS_READY if self.params.enabled else STATUS_DISABLED,
            "output_dir": str(self.output_dir),
            "resolutions": self.params.snapshot()["derived"]["resolutions"],
            "required_elements": [
                "candles",
                "symbol",
                "timeframe",
                "timestamp",
                "price",
                "levels",
                "zones",
                "annotations",
                "pattern_name",
                "confluence",
            ],
            "stats": self.stats(),
        }

    @staticmethod
    def _metadata_from_row(row: dict) -> CaptureMetadata:
        stamp = row.get("timestamp")
        return CaptureMetadata(
            capture_id=row["id"],
            opportunity_id=row.get("opportunity_id"),
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            timestamp=datetime.fromisoformat(stamp) if isinstance(stamp, str) else (stamp or datetime.now(tz=timezone.utc)),
            path=row["path"],
            hash=row.get("digest") or "",
            width=row.get("width") or 0,
            height=row.get("height") or 0,
            resolution="phone",
            bytes=row.get("size_bytes") or 0,
            overlay_count=len((row.get("overlays") or {}).get("items", [])),
            dedup_key=row["id"],
        )


def _overlays_json(scene: CaptureScene) -> str:
    import json

    return json.dumps(
        {
            "items": [
                {
                    "kind": item.kind.value,
                    "label": item.label,
                    "priority": item.priority,
                    "source": item.source,
                    "source_id": item.source_id,
                }
                for item in scene.overlays
            ],
            "dropped": scene.notes,
        },
        ensure_ascii=False,
    )[:4000]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(function, default=-1):
    try:
        return function()
    except Exception as exc:  # pragma: no cover - locked database
        logger.error("Capture count failed: %s", exc)
        return default


#: application-wide instance (the container replaces it in tests)
capture_service = CaptureService()
