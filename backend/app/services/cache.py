"""Caching, and the one place it was actually costing something.

The benchmark table is read with ``json.loads`` on **every** SWOT run, every
``GET /methodology`` and every ``GET /benchmarks/provenance``. The shipped
EDGAR table is 11 KB of JSON across fifteen sectors and it never changes
between deploys, so that is a file read plus a parse plus the construction of a
``BenchmarkTable`` on every single one of those requests.

Two caches live here.

``TTLCache`` is the general one: bounded, thread-safe, with hit/miss counters
wired into the metrics registry so the hit rate is visible rather than assumed.

``benchmark_table`` is the specific one, and it is **not** a TTL cache. A TTL on
a file is a guess: too short and you keep paying, too long and an operator who
swaps the table waits for an arbitrary clock. It keys on
``(path, mtime_ns, size)`` instead, so a rebuilt table is picked up on the next
request with no configuration and no restart, and an unchanged file is never
parsed twice.

**Both are per-process.** Behind several workers each has its own copy, which
is correct for immutable derived data and would be wrong for anything shared
and mutable. Where that stops being true, the answer is Redis and this module
is the seam to put it behind - not a bigger dictionary.
"""

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

        # The factory runs OUTSIDE the lock. Holding a lock across a file read
        # or a database query turns a cache into a global serialisation point,
        # which is a worse problem than the one it was added to solve. The cost
        # is that two racing misses both compute; the value is identical, so
        # the only loss is one duplicated computation.
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
    """``(path, mtime_ns, size)``, or a marker for the built-in table.

    mtime **and** size: mtime alone can miss an edit that lands inside the
    filesystem's timestamp granularity, and a rebuilt benchmark table that
    changes a median without changing its byte count is exactly the kind of
    edit that would slip through.
    """
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
    """A weak ETag over a JSON-serialisable payload.

    Weak, because the bytes a client received depend on serialiser details this
    function does not control; the *meaning* is what is being compared.
    """
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f'W/"{digest[:32]}"'
