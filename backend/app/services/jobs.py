"""Background jobs, because some of this work does not fit in a request.

Building the benchmark table makes hundreds of rate-limited requests to
data.sec.gov and takes minutes. V3 handled that by refusing to expose it at
all: ``POST /benchmarks/build`` returned 501 with instructions to run a CLI.
That was the right call over doing it *inside* a request handler - a five
minute synchronous HTTP call is not an API, it is a timeout with a body - but
"run this by hand on the server" is not a feature either.

This is the missing middle: the request enqueues work and returns **202 with a
job id**, a worker pool runs it, and the client polls. The pieces that make it
a job system rather than a thread:

* **The row is the source of truth**, not the future. A job's state lives in
  ``jobs``, so a restart does not lose the record of what ran, what it
  produced, and what it cost.
* **Heartbeats.** A worker updates ``heartbeat_at`` as it progresses. A job
  whose heartbeat has gone stale is reaped and marked FAILED, so a crashed
  worker cannot leave a row RUNNING forever - which is the failure mode that
  makes people distrust a queue.
* **Cancellation is cooperative.** ``POST /jobs/{id}/cancel`` sets a flag the
  running function checks. Killing a thread mid-write is how you get a
  half-written benchmark file.
* **Progress and logs.** Long jobs report a fraction and a message, so the UI
  can show "classified 900/1500" instead of a spinner.
* **Deduplication.** An identical job already queued or running is returned
  rather than started twice, because two concurrent EDGAR rebuilds writing the
  same file is a corrupted file.

**What this is not.** It is an in-process pool, so jobs do not survive a
restart mid-flight (they are reaped and marked FAILED on the next boot) and
they do not spread across workers. That is the honest trade for zero new
infrastructure. The seam is ``submit()``: swapping in Celery or RQ means
changing this module and nothing that calls it.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import Settings
from app.db.session import SessionLocal
from app.enums import JobState
from app.models import Job
from app.obs import METRICS, new_request_id

logger = logging.getLogger("strategysphere.jobs")


class JobCancelled(Exception):
    """Raised inside a job when the caller asked it to stop."""


@dataclass
class JobContext:
    """Handed to every job function: progress, logging, and the stop signal."""

    job_id: uuid.UUID
    _cancel: threading.Event
    _last_write: float = field(default=0.0)
    _progress: float = 0.0
    _message: str = ""

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def progress(self, fraction: float, message: str = "") -> None:
        """Report progress, and heartbeat while doing it.

        Writes are throttled to once a second: a job that updates a row on
        every one of fifteen hundred EDGAR calls spends more time in the
        database than on the work.
        """
        self.check_cancelled()
        self._progress = max(0.0, min(1.0, float(fraction)))
        if message:
            self._message = message
        now = time.monotonic()
        if now - self._last_write < 1.0 and self._progress < 1.0:
            return
        self._last_write = now
        _update(
            self.job_id,
            progress=self._progress,
            message=self._message,
            heartbeat_at=datetime.now(timezone.utc),
        )

    def log(self, message: str) -> None:
        logger.info("job progress", extra={"ctx_job_id": str(self.job_id), "ctx_msg": message})
        self.progress(self._progress, message)


JobFunc = Callable[[JobContext, dict[str, Any], Settings], dict[str, Any]]
_REGISTRY: dict[str, JobFunc] = {}


def register(kind: str) -> Callable[[JobFunc], JobFunc]:
    """Register a job function under a stable kind string."""

    def decorator(func: JobFunc) -> JobFunc:
        _REGISTRY[kind] = func
        return func

    return decorator


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

_executor: ThreadPoolExecutor | None = None
_cancels: dict[uuid.UUID, threading.Event] = {}
_lock = threading.Lock()
_reaper: threading.Thread | None = None
_stopping = threading.Event()
_settings: Settings | None = None


def _update(job_id: uuid.UUID, **fields: Any) -> None:
    """Write job fields in their own short-lived session.

    A worker must not share the request's session: the request is long gone by
    the time a five-minute job writes its third progress update.
    """
    with SessionLocal() as db:
        row = db.get(Job, job_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def start_runner(settings: Settings) -> None:
    # Importing the task module is what registers the kinds. Done here rather
    # than at module import so the runner and its work cannot import-cycle.
    from app.services import job_tasks  # noqa: F401

    global _executor, _reaper, _settings
    with _lock:
        if _executor is not None:
            return
        _settings = settings
        _stopping.clear()
        _executor = ThreadPoolExecutor(
            max_workers=settings.job_workers, thread_name_prefix="job"
        )
        # Anything left RUNNING belongs to a process that no longer exists.
        _reap_orphans(settings, reason="the worker process restarted")
        _reaper = threading.Thread(target=_reap_loop, args=(settings,), daemon=True)
        _reaper.start()
    logger.info("job runner started", extra={"ctx_workers": settings.job_workers})


def shutdown_runner(wait: bool = True) -> None:
    global _executor, _reaper
    with _lock:
        executor, _executor = _executor, None
        _reaper = None
    _stopping.set()
    if executor is not None:
        executor.shutdown(wait=wait)
        logger.info("job runner stopped")


def runner_status() -> dict[str, Any]:
    with _lock:
        running = len(_cancels)
        workers = _executor._max_workers if _executor else 0   # noqa: SLF001
    return {"ok": _executor is not None, "workers": workers, "in_flight": running}


def _reap_loop(settings: Settings) -> None:
    while not _stopping.wait(timeout=15.0):
        try:
            _reap_orphans(settings, reason="the job stopped heartbeating")
        except Exception:  # noqa: BLE001 - a reaper that dies silently is worse
            logger.exception("reaper failed")


def _reap_orphans(settings: Settings, *, reason: str) -> int:
    """Fail every RUNNING job whose heartbeat has gone stale."""
    from sqlalchemy import select

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.job_heartbeat_timeout_seconds
    )
    reaped = 0
    with SessionLocal() as db:
        rows = db.scalars(select(Job).where(Job.state == JobState.RUNNING.value)).all()
        for row in rows:
            beat = row.heartbeat_at or row.started_at
            if beat is not None and beat.tzinfo is None:
                beat = beat.replace(tzinfo=timezone.utc)
            if beat is not None and beat > cutoff:
                continue
            with _lock:
                if row.id in _cancels:
                    # Still ours and still alive; the heartbeat is merely
                    # overdue because the job is inside a long blocking call.
                    continue
            row.state = JobState.FAILED.value
            row.error = f"Job was reaped: {reason}."
            row.finished_at = datetime.now(timezone.utc)
            reaped += 1
        if reaped:
            db.commit()
            METRICS.inc("jobs_reaped_total", value=reaped)
            logger.warning("reaped stale jobs", extra={"ctx_count": reaped, "ctx_reason": reason})
    return reaped


def _run(job_id: uuid.UUID, kind: str, params: dict[str, Any], settings: Settings) -> None:
    cancel = threading.Event()
    with _lock:
        _cancels[job_id] = cancel

    started = time.perf_counter()
    _update(
        job_id,
        state=JobState.RUNNING.value,
        started_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
    )
    context = JobContext(job_id=job_id, _cancel=cancel)

    try:
        func = _REGISTRY[kind]
        result = func(context, params, settings)
        _update(
            job_id,
            state=JobState.SUCCEEDED.value,
            progress=1.0,
            result=result,
            finished_at=datetime.now(timezone.utc),
            duration_seconds=round(time.perf_counter() - started, 3),
        )
        METRICS.inc("jobs_total", {"kind": kind, "state": "succeeded"})
    except JobCancelled:
        _update(
            job_id,
            state=JobState.CANCELLED.value,
            error="Cancelled by request.",
            finished_at=datetime.now(timezone.utc),
            duration_seconds=round(time.perf_counter() - started, 3),
        )
        METRICS.inc("jobs_total", {"kind": kind, "state": "cancelled"})
    except Exception as exc:  # noqa: BLE001 - the traceback is the payload
        _update(
            job_id,
            state=JobState.FAILED.value,
            error=f"{type(exc).__name__}: {exc}",
            result={"traceback": traceback.format_exc()[-4000:]},
            finished_at=datetime.now(timezone.utc),
            duration_seconds=round(time.perf_counter() - started, 3),
        )
        METRICS.inc("jobs_total", {"kind": kind, "state": "failed"})
        logger.exception("job failed", extra={"ctx_job_id": str(job_id), "ctx_kind": kind})
    finally:
        METRICS.observe(
            "job_duration_seconds", time.perf_counter() - started, {"kind": kind}
        )
        with _lock:
            _cancels.pop(job_id, None)


def submit(
    db,
    kind: str,
    params: dict[str, Any] | None = None,
    *,
    settings: Settings,
    dedupe: bool = True,
) -> Job:
    """Enqueue a job, or return the identical one already in flight.

    Deduplication is on ``(kind, params)`` across QUEUED and RUNNING. Two
    concurrent EDGAR rebuilds would write the same file from two threads, and
    the second caller almost always wants the first one's result anyway.
    """
    from sqlalchemy import select

    if kind not in _REGISTRY:
        raise KeyError(f"unknown job kind '{kind}'; known: {sorted(_REGISTRY)}")

    payload = params or {}

    if dedupe:
        existing = db.scalars(
            select(Job)
            .where(
                Job.kind == kind,
                Job.state.in_([JobState.QUEUED.value, JobState.RUNNING.value]),
            )
            .order_by(Job.created_at.desc())
        ).all()
        for candidate in existing:
            if (candidate.params or {}) == payload:
                return candidate

    row = Job(
        id=uuid.uuid4(),
        kind=kind,
        state=JobState.QUEUED.value,
        params=payload,
        request_id=new_request_id(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    METRICS.inc("jobs_total", {"kind": kind, "state": "queued"})

    with _lock:
        executor = _executor
    if executor is None:
        # No runner (a test, or a CLI import). Leaving the row QUEUED is more
        # honest than pretending it ran.
        logger.warning("job queued with no runner", extra={"ctx_kind": kind})
        return row

    executor.submit(_run, row.id, kind, payload, settings)
    return row


def cancel(db, job_id: uuid.UUID) -> bool:
    """Ask a job to stop. Returns False if it was already finished.

    The ownership rule is what makes this safe: **whoever is running the job
    writes its terminal state.** If a worker has the job, cancelling only sets
    the flag and the worker records CANCELLED when it next checks. Only a job
    that no worker has claimed is written to directly here.

    That rule is not decorative. Without it, this function read ``row.state``
    from the caller's session - which can be a cached QUEUED while the worker
    has already moved the row to RUNNING in its own session - took the "never
    started" branch, and overwrote the worker's state from a second connection.
    Two writers, last one wins, and the job's recorded outcome depended on
    thread timing.
    """
    row = db.get(Job, job_id)
    if row is None:
        return False

    # Refresh before deciding: another session owns this row while it runs.
    db.refresh(row)
    if row.state in {
        JobState.SUCCEEDED.value,
        JobState.FAILED.value,
        JobState.CANCELLED.value,
    }:
        return False

    with _lock:
        event = _cancels.get(job_id)

    if event is not None:
        # A worker holds it. Signal and let it write its own terminal state.
        event.set()
        return True

    if row.state == JobState.QUEUED.value:
        # Unclaimed, so there is nothing to interrupt cooperatively and this
        # session is the only writer.
        row.state = JobState.CANCELLED.value
        row.error = "Cancelled before it started."
        row.finished_at = datetime.now(timezone.utc)
        db.commit()
        return True

    # RUNNING with no cancel event: the worker died between claiming the row
    # and registering, or this process is not the one running it. The reaper
    # owns that case; saying True here would promise a stop nobody will make.
    return False


def purge_old(db, older_than_days: int) -> int:
    """Delete finished jobs past the retention window."""
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    result = db.execute(
        delete(Job).where(
            Job.finished_at.is_not(None),
            Job.finished_at < cutoff,
        )
    )
    db.commit()
    return int(result.rowcount or 0)
