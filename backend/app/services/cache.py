"""In-memory TTL cache for candle series.

Purpose: keep the upstream request rate low while the dashboard polls and the
scanner ticks. A cached entry is real data fetched from the provider - it is
only ever consumed while its TTL is valid.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.schemas.market import CandleSeries, Timeframe, as_timeframe


@dataclass
class CacheEntry:
    value: CandleSeries
    stored_at: float
    ttl: float
    hits: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def age(self) -> float:
        return time.monotonic() - self.stored_at

    @property
    def expired(self) -> bool:
        return self.age >= self.ttl


class SeriesCache:
    def __init__(self, max_entries: int = 512) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    @staticmethod
    def key(symbol: str, timeframe: "Timeframe | str", limit: int) -> str:
        return f"{symbol.upper()}:{as_timeframe(timeframe).value}:{limit}"

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.expired:
                return None
            entry.hits += 1
            return entry

    def peek(self, key: str) -> CacheEntry | None:
        """Return the entry even when expired (used for stale fallback)."""
        with self._lock:
            return self._entries.get(key)

    def set(self, key: str, value: CandleSeries, ttl: float) -> CacheEntry:
        entry = CacheEntry(value=value, stored_at=time.monotonic(), ttl=ttl)
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest = sorted(self._entries.items(), key=lambda kv: kv[1].stored_at)
                for stale_key, _ in oldest[: max(1, self._max_entries // 10)]:
                    self._entries.pop(stale_key, None)
            self._entries[key] = entry
        return entry

    def invalidate(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "hits": sum(e.hits for e in self._entries.values()),
                "keys": sorted(self._entries),
            }


series_cache = SeriesCache()


#: explicit alias used by MarketService
SeriesCacheEntry = CacheEntry
