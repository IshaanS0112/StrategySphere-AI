"""Caches for derived data: a bounded TTL cache and the benchmark table."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generic, Hashable, TypeVar

from app.obs import METRICS

V = TypeVar("V")


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
        }


class TTLCache(Generic[V]):
    """A bounded TTL cache. LRU eviction, one lock, counters on the registry."""

    def __init__(self, name: str, *, maxsize: int = 256, ttl_seconds: float = 300.0) -> None:
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[Hashable, tuple[float, V]] = {}
        # Insertion order is the LRU order; a hit moves the key to the end.
        self.stats = CacheStats()

    def get_or_set(self, key: Hashable, factory: Callable[[], V]) -> V:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and entry[0] > now:
                self._store[key] = self._store.pop(key)   # refresh LRU position
                self.stats.hits += 1
                METRICS.inc("cache_hits_total", {"cache": self.name})
                return entry[1]
            if entry is not None:
                del self._store[key]

        # The factory runs OUTSIDE the lock.
        value = factory()

        with self._lock:
            self._store[key] = (now + self.ttl, value)
            while len(self._store) > self.maxsize:
                self._store.pop(next(iter(self._store)))
                self.stats.evictions += 1
                METRICS.inc("cache_evictions_total", {"cache": self.name})
            self.stats.misses += 1
        METRICS.inc("cache_misses_total", {"cache": self.name})
        return value

    def invalidate(self, key: Hashable | None = None) -> None:
        with self._lock:
            if key is None:
                self._store.clear()
            else:
                self._store.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# --------------------------------------------------------------------------
# The benchmark table
# --------------------------------------------------------------------------

_benchmark_lock = threading.Lock()
_benchmark_entry: tuple[tuple[Any, ...], Any] | None = None
BENCHMARK_STATS = CacheStats()


def _file_signature(path: str) -> tuple[Any, ...]:
    """``(path, mtime_ns, size)``, or a marker for the built-in table."""
    if not path:
        return ("<built-in>",)
    try:
        stat = Path(path).stat()
    except OSError:
        return (path, "missing")
    return (path, stat.st_mtime_ns, stat.st_size)


def benchmark_table(path: str | None) -> Any:
    """The loaded ``BenchmarkTable`` for ``path``, parsed at most once per version."""
    from app.services import benchmarks as bench

    key = _file_signature(path or "")
    global _benchmark_entry

    with _benchmark_lock:
        entry = _benchmark_entry
        if entry is not None and entry[0] == key:
            BENCHMARK_STATS.hits += 1
            METRICS.inc("cache_hits_total", {"cache": "benchmark_table"})
            return entry[1]

    table = bench.load_benchmark_table(path)

    with _benchmark_lock:
        _benchmark_entry = (key, table)
        BENCHMARK_STATS.misses += 1
    METRICS.inc("cache_misses_total", {"cache": "benchmark_table"})
    return table


def invalidate_benchmark_table() -> None:
    """Drop the cached table. Called after a rebuild writes a new file."""
    global _benchmark_entry
    with _benchmark_lock:
        _benchmark_entry = None


def stats() -> dict[str, Any]:
    return {"benchmark_table": BENCHMARK_STATS.to_dict()}


# --------------------------------------------------------------------------
# HTTP validators
# --------------------------------------------------------------------------


def etag_for(payload: Any) -> str:
    """A weak ETag over a JSON-serialisable payload."""
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f'W/"{digest[:32]}"'
