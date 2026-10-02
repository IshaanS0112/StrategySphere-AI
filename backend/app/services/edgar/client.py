"""Rate-limited, User-Agent-enforced, disk-cached client for data.sec.gov."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Anything outside these hosts is out of scope for this project by design.
ALLOWED_HOSTS = ("data.sec.gov", "www.sec.gov")


class EdgarConfigError(RuntimeError):
    """The client cannot be built as configured."""


class EdgarOfflineError(RuntimeError):
    """Offline mode was asked for a URL that is not in the cache."""


class EdgarFetchError(RuntimeError):
    """The request reached the network and did not come back usable."""


def validate_user_agent(raw: str | None) -> str:
    """Return a usable User-Agent or explain precisely why there is not one."""
    candidate = (raw or "").strip()
    if not candidate:
        raise EdgarConfigError(
            "EDGAR_USER_AGENT is not set. The SEC requires automated access to "
            "data.sec.gov to declare a User-Agent identifying the requester with "
            "contact details, for example:\n"
            '    EDGAR_USER_AGENT="Jane Doe jane@example.com"\n'
            "There is deliberately no default. An anonymous request to SEC "
            "infrastructure is a compliance problem, not a convenience, so this "
            "client refuses to be constructed without one."
        )
    if "@" not in candidate:
        raise EdgarConfigError(
            f"EDGAR_USER_AGENT={candidate!r} carries no contact address. SEC guidance "
            "asks for a name and a reachable email, e.g. 'Jane Doe jane@example.com'. "
            "A bare product name identifies nobody."
        )
    return candidate


class TokenBucket:
    """Rate limiter with an explicit, and by default absent, burst allowance."""

    def __init__(
        self,
        rate_per_second: float,
        *,
        burst: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise EdgarConfigError("rate_per_second must be positive")
        if burst < 1:
            raise EdgarConfigError("burst must be at least 1")
        self.rate = float(rate_per_second)
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()
        self.waits: list[float] = []

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def take(self) -> float:
        """Consume one token, blocking if necessary. Returns the seconds waited."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self.waits.append(0.0)
                return 0.0
            deficit = 1.0 - self._tokens
            wait = deficit / self.rate
            # Reserve now: the balance goes negative and the next caller's wait
            # is computed from there, which is what spaces concurrent callers.
            self._tokens -= 1.0
            self.waits.append(wait)

        self._sleep(wait)
        return wait


@dataclass
class FetchStats:
    requests_made: int = 0
    cache_hits: int = 0
    cache_writes: int = 0
    seconds_waiting: float = 0.0
    failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests_made": self.requests_made,
            "cache_hits": self.cache_hits,
            "cache_writes": self.cache_writes,
            "seconds_waiting": round(self.seconds_waiting, 3),
            "failures": self.failures,
        }


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


class EdgarClient:
    """The only thing in this project permitted to talk to the SEC."""

    def __init__(
        self,
        *,
        user_agent: str | None,
        cache_dir: str | Path,
        requests_per_second: float = 5.0,
        burst: float = 1.0,
        timeout_seconds: float = 30.0,
        offline: bool = False,
        concurrency: int = 1,
        transport: Callable[[str, dict[str, str], float], bytes] = _default_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # Offline mode never touches the network, so it does not need a User-Agent -
        # and demanding one would make cached fixtures unusable in CI, where there
        # are no contact details to supply.
        self.offline = bool(offline)
        self.user_agent = "" if self.offline else validate_user_agent(user_agent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        self.bucket = TokenBucket(requests_per_second, burst=burst, clock=clock, sleep=sleep)
        self._transport = transport
        self.concurrency = max(1, int(concurrency))
        self._stats_lock = threading.Lock()
        self.stats = FetchStats()

    # --- cache ------------------------------------------------------------

    def cache_path(self, url: str) -> Path:
        """Content-addressed by URL."""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        tail = url.rstrip("/").split("/")[-1].replace(".json", "")[:60]
        safe_tail = "".join(c if c.isalnum() or c in "-_" else "-" for c in tail)
        return self.cache_dir / f"{digest}-{safe_tail}.json"

    def cached(self, url: str) -> dict[str, Any] | None:
        path = self.cache_path(url)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            # A truncated cache entry is worse than no cache entry: it would be
            # served forever. Drop it and let the caller refetch.
            logger.warning("Discarding unreadable cache entry %s (%s)", path, exc)
            path.unlink(missing_ok=True)
            return None

    # --- fetch ------------------------------------------------------------

    def get_json(self, url: str) -> dict[str, Any]:
        if not any(url.startswith(f"https://{host}/") for host in ALLOWED_HOSTS):
            raise EdgarConfigError(
                f"Refusing to fetch {url}: this client only talks to {ALLOWED_HOSTS}. "
                "Scraping anything else is out of scope for this project by design."
            )

        hit = self.cached(url)
        if hit is not None:
            with self._stats_lock:
                self.stats.cache_hits += 1
            return hit

        if self.offline:
            raise EdgarOfflineError(
                f"offline=True and {url} is not cached (expected at "
                f"{self.cache_path(url)}). Run the build once with network access to "
                "populate the cache, or pass the fixture directory as the cache dir. "
                "Offline mode never silently reaches out."
            )

        waited = self.bucket.take()
        with self._stats_lock:
            self.stats.seconds_waiting += waited
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            # Explicitly identity: urllib does not transparently decompress, and a
            # gzip body parsed as JSON fails in a way that looks like the SEC
            # returned garbage.
            "Accept-Encoding": "identity",
        }
        try:
            raw = self._transport(url, headers, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            with self._stats_lock:
                self.stats.failures += 1
            raise EdgarFetchError(f"{url} returned HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            with self._stats_lock:
                self.stats.failures += 1
            raise EdgarFetchError(f"{url} could not be fetched: {exc}") from exc

        with self._stats_lock:
            self.stats.requests_made += 1
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            with self._stats_lock:
                self.stats.failures += 1
            raise EdgarFetchError(f"{url} did not return JSON: {exc}") from exc

        self.cache_path(url).write_text(json.dumps(payload))
        with self._stats_lock:
            self.stats.cache_writes += 1
        return payload

    # --- the three endpoints ----------------------------------------------

    def get_many(
        self,
        urls: Sequence[str],
        *,
        on_result: Callable[[str, dict[str, Any] | None, Exception | None], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch many URLs with bounded concurrency, still rate-limited."""
        results: dict[str, dict[str, Any]] = {}
        if not urls:
            return results

        lock = threading.Lock()

        def fetch(url: str) -> None:
            try:
                payload = self.get_json(url)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                if on_result:
                    on_result(url, None, exc)
                return
            with lock:
                results[url] = payload
            if on_result:
                on_result(url, payload, None)

        workers = min(self.concurrency, len(urls))
        if workers <= 1:
            for url in urls:
                fetch(url)
            return results

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="edgar") as pool:
            list(pool.map(fetch, urls))
        return results

    def submissions_many(
        self,
        ciks: Iterable[int],
        *,
        on_result: Callable[[str, dict[str, Any] | None, Exception | None], None] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """``{cik: submissions payload}`` for many companies, concurrently."""
        url_by_cik = {int(cik): SUBMISSIONS_URL.format(cik=int(cik)) for cik in ciks}
        fetched = self.get_many(list(url_by_cik.values()), on_result=on_result)
        return {cik: fetched[url] for cik, url in url_by_cik.items() if url in fetched}

    def frames(
        self, concept: str, *, unit: str = "USD", period: str = "CY2024", taxonomy: str = "us-gaap"
    ) -> dict[str, Any]:
        """One fact for every reporting entity for one period."""
        return self.get_json(
            FRAMES_URL.format(taxonomy=taxonomy, concept=concept, unit=unit, period=period)
        )

    def companyfacts(self, cik: int) -> dict[str, Any]:
        """Every concept for one company. Used for focal companies, not panels."""
        return self.get_json(COMPANYFACTS_URL.format(cik=int(cik)))

    def submissions(self, cik: int) -> dict[str, Any]:
        """Filing history, ticker and SIC code. One request per company."""
        return self.get_json(SUBMISSIONS_URL.format(cik=int(cik)))


def client_from_settings(settings: Any, *, offline: bool | None = None) -> EdgarClient:
    """Build a client from ``Settings``, honouring an explicit offline override."""
    return EdgarClient(
        user_agent=settings.edgar_user_agent,
        cache_dir=settings.edgar_cache_dir,
        requests_per_second=settings.edgar_requests_per_second,
        timeout_seconds=settings.edgar_timeout_seconds,
        offline=settings.edgar_offline if offline is None else offline,
        concurrency=getattr(settings, "edgar_concurrency", 1),
    )
