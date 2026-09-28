"""Request identity, structured logs, and metrics - with no new dependencies.

V3 logged with ``logging.basicConfig`` and a human format. That is readable on
one developer's terminal and unusable everywhere else: there is no way to tie
three log lines to the same request, no way to find the slow endpoint, and no
way to answer "how often does the matrix 409 because nobody ran the SWOT" short
of grepping prose.

Three things fix that, and all three are stdlib:

**A request id on everything.** Taken from an inbound ``X-Request-ID`` when a
proxy already assigned one - so a trace survives the hop - and generated
otherwise. It goes on the response header, into every log line emitted while
that request is in flight, and into the ``request_id`` field of any problem
document, which is what makes a user's screenshot of an error actionable.

**JSON logs.** One object per line, with the request id, route, method, status
and duration. ``LOG_FORMAT=text`` restores the human format for local work,
because JSON in a terminal is its own kind of unreadable.

**Prometheus metrics, hand-rolled.** ``/metrics`` emits the standard text
exposition format from three in-process collectors. A real deployment would use
``prometheus_client``; that is one more dependency for about forty lines of
formatting, and this project's tests run on a bare clone with pytest and
nothing else. The limitation is stated in the endpoint's own docstring: these
counters are per-process, so behind more than one worker you are reading one
worker's view.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context-local rather than thread-local: FastAPI runs handlers on an event
# loop, so a thread can serve several requests and thread-locals would leak the
# wrong id between them.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_route: ContextVar[str] = ContextVar("route", default="-")

REQUEST_ID_HEADER = "X-Request-ID"


def current_request_id() -> str:
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

# Seconds. Chosen around what this application actually does: sub-10ms reads,
# ~100ms scoring runs, and the multi-second tail where an LLM call or a Monte
# Carlo lands.
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class Metrics:
    """Counters, gauges and histograms, guarded by one lock."""

    def __init__(self, buckets: tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._hists: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}
        self._buckets = buckets

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None):
        return name, tuple(sorted((labels or {}).items()))

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            key = self._key(name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._hists.setdefault(self._key(name, labels), []).append(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {k: list(v) for k, v in self._hists.items()},
            }

    def reset(self) -> None:
        """Only used by tests. A process that resets its own counters in
        production is a process that lies to its dashboard."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._hists.clear()

    # --- exposition -------------------------------------------------------

    @staticmethod
    def _labels_str(labels: tuple[tuple[str, str], ...], extra: dict[str, str] | None = None) -> str:
        merged = dict(labels)
        merged.update(extra or {})
        if not merged:
            return ""
        inner = ",".join(
            f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
            for k, v in sorted(merged.items())
        )
        return "{" + inner + "}"

    def render(self) -> str:
        """Prometheus text exposition format, version 0.0.4."""
        snap = self.snapshot()
        lines: list[str] = []

        seen: set[str] = set()
        for (name, labels), value in sorted(snap["counters"].items()):
            if name not in seen:
                lines.append(f"# TYPE {name} counter")
                seen.add(name)
            lines.append(f"{name}{self._labels_str(labels)} {value:g}")

        for (name, labels), value in sorted(snap["gauges"].items()):
            if name not in seen:
                lines.append(f"# TYPE {name} gauge")
                seen.add(name)
            lines.append(f"{name}{self._labels_str(labels)} {value:g}")

        for (name, labels), values in sorted(snap["histograms"].items()):
            if name not in seen:
                lines.append(f"# TYPE {name} histogram")
                seen.add(name)
            ordered = sorted(values)
            cumulative = 0
            index = 0
            for edge in self._buckets:
                while index < len(ordered) and ordered[index] <= edge:
                    index += 1
                    cumulative += 1
                lines.append(
                    f"{name}_bucket{self._labels_str(labels, {'le': repr(edge)})} {cumulative}"
                )
            lines.append(f"{name}_bucket{self._labels_str(labels, {'le': '+Inf'})} {len(ordered)}")
            lines.append(f"{name}_sum{self._labels_str(labels)} {sum(ordered):g}")
            lines.append(f"{name}_count{self._labels_str(labels)} {len(ordered)}")

        return "\n".join(lines) + "\n"


METRICS = Metrics()


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the request context folded in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id.get(),
        }
        route = _route.get()
        if route != "-":
            payload["route"] = route
        # Anything passed as extra={...} rides along, which is how the access
        # log gets status and duration without a second format string.
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn's own access log duplicates the middleware's, with less in it.
    logging.getLogger("uvicorn.access").disabled = True


# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------

logger = logging.getLogger("strategysphere.access")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Assigns the request id, times the request, logs it, counts it."""

    def __init__(self, app, slow_request_seconds: float = 1.0) -> None:
        super().__init__(app)
        self.slow_request_seconds = slow_request_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[:64] if incoming else new_request_id()
        token = _request_id.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # The exception handlers turn known failures into responses, so
            # anything arriving here is genuinely unhandled and worth a count
            # of its own rather than being lost in the 5xx bucket.
            METRICS.inc("http_unhandled_exceptions_total")
            logger.exception(
                "unhandled exception",
                extra={"ctx_method": request.method, "ctx_path": request.url.path},
            )
            raise
        finally:
            duration = time.perf_counter() - started
            # The route TEMPLATE, not the path: a per-id label set is an
            # unbounded cardinality explosion, which is the classic way to
            # take down a metrics backend with your own instrumentation.
            route = request.scope.get("route")
            template = getattr(route, "path", request.url.path)
            _route.set(template)
            labels = {"method": request.method, "route": template, "status": str(status_code)}
            METRICS.inc("http_requests_total", labels)
            METRICS.observe(
                "http_request_duration_seconds",
                duration,
                {"method": request.method, "route": template},
            )
            level = logging.WARNING if duration >= self.slow_request_seconds else logging.INFO
            logger.log(
                level,
                "request",
                extra={
                    "ctx_method": request.method,
                    "ctx_path": request.url.path,
                    "ctx_route": template,
                    "ctx_status": status_code,
                    "ctx_duration_ms": round(duration * 1000, 2),
                    "ctx_slow": duration >= self.slow_request_seconds,
                },
            )
            _request_id.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={round(duration * 1000, 2)}"
        return response
