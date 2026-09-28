"""The job system: lifecycle, cancellation, deduplication, and the reaper.

The reaper is the part worth testing hardest. A queue that can leave a row
RUNNING forever is a queue people stop trusting, and the only way that bug
surfaces in production is as a job that never finishes and nobody can explain.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.enums import JobState
from app.models import Job
from app.services import jobs


@pytest.fixture
def runner(db_session):
    """A live runner with two workers, torn down after the test."""
    db, _engine = db_session
    settings = Settings(_env_file=None, job_workers=2, job_heartbeat_timeout_seconds=0.2)
    jobs.shutdown_runner(wait=False)
    jobs.start_runner(settings)
    try:
        yield db, settings
    finally:
        jobs.shutdown_runner(wait=False)


def wait_for(db, job_id, states, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        db.expire_all()
        row = db.get(Job, job_id)
        if row is not None and row.state in states:
            return row
        time.sleep(0.02)
    db.expire_all()
    row = db.get(Job, job_id)
    raise AssertionError(f"job stuck in {row.state if row else 'missing'}; wanted {states}")


class TestLifecycle:
    def test_a_job_runs_and_records_its_result(self, runner):
        db, settings = runner

        @jobs.register("test.ok")
        def _ok(context, params, _settings):
            context.progress(0.5, "halfway")
            return {"doubled": params["n"] * 2}

        row = jobs.submit(db, "test.ok", {"n": 21}, settings=settings, dedupe=False)
        assert row.state == JobState.QUEUED.value

        done = wait_for(db, row.id, {JobState.SUCCEEDED.value})
        assert done.result == {"doubled": 42}
        assert done.progress == 1.0
        assert done.duration_seconds is not None
        assert done.finished_at is not None

    def test_a_failure_is_recorded_rather_than_lost(self, runner):
        db, settings = runner

        @jobs.register("test.boom")
        def _boom(_context, _params, _settings):
            raise ValueError("the upstream said no")

        row = jobs.submit(db, "test.boom", {}, settings=settings, dedupe=False)
        done = wait_for(db, row.id, {JobState.FAILED.value})
        assert "ValueError: the upstream said no" == done.error
        # The traceback is kept, because "it failed" is not a bug report.
        assert "Traceback" in done.result["traceback"]

    def test_an_unknown_kind_is_refused_at_submit(self, runner):
        db, settings = runner
        with pytest.raises(KeyError) as exc:
            jobs.submit(db, "test.nope", {}, settings=settings)
        assert "unknown job kind" in str(exc.value)

    def test_progress_is_visible_while_it_runs(self, runner):
        db, settings = runner
        release = threading.Event()

        @jobs.register("test.slow")
        def _slow(context, _params, _settings):
            context.progress(0.25, "working")
            release.wait(timeout=3)
            return {}

        row = jobs.submit(db, "test.slow", {}, settings=settings, dedupe=False)
        running = wait_for(db, row.id, {JobState.RUNNING.value})
        deadline = time.time() + 2
        while time.time() < deadline and (running.progress or 0) == 0:
            db.expire_all()
            running = db.get(Job, row.id)
            time.sleep(0.02)
        assert running.progress == pytest.approx(0.25)
        assert running.message == "working"
        release.set()
        wait_for(db, row.id, {JobState.SUCCEEDED.value})


class TestCancellation:
    def test_a_running_job_stops_at_its_next_checkpoint(self, runner):
        db, settings = runner
        started = threading.Event()

        @jobs.register("test.cancellable")
        def _cancellable(context, _params, _settings):
            started.set()
            for _ in range(500):
                context.check_cancelled()
                time.sleep(0.01)
            return {"finished": True}

        row = jobs.submit(db, "test.cancellable", {}, settings=settings, dedupe=False)
        assert started.wait(timeout=3)
        assert jobs.cancel(db, row.id) is True
        done = wait_for(db, row.id, {JobState.CANCELLED.value})
        assert done.error == "Cancelled by request."

    def test_a_finished_job_cannot_be_cancelled(self, runner):
        db, settings = runner

        @jobs.register("test.quick")
        def _quick(_context, _params, _settings):
            return {}

        row = jobs.submit(db, "test.quick", {}, settings=settings, dedupe=False)
        wait_for(db, row.id, {JobState.SUCCEEDED.value})
        assert jobs.cancel(db, row.id) is False

    def test_cancelling_an_unknown_job_is_false_not_an_exception(self, runner):
        db, _settings = runner
        assert jobs.cancel(db, uuid.uuid4()) is False


class TestDeduplication:
    def test_an_identical_job_in_flight_is_reused(self, runner):
        db, settings = runner
        release = threading.Event()

        @jobs.register("test.dedupe")
        def _dedupe(_context, _params, _settings):
            release.wait(timeout=3)
            return {}

        first = jobs.submit(db, "test.dedupe", {"period": "CY2024"}, settings=settings)
        second = jobs.submit(db, "test.dedupe", {"period": "CY2024"}, settings=settings)
        # Two concurrent EDGAR rebuilds writing the same file is a corrupt file.
        assert first.id == second.id
        release.set()
        wait_for(db, first.id, {JobState.SUCCEEDED.value})

    def test_different_params_are_different_jobs(self, runner):
        db, settings = runner
        release = threading.Event()

        @jobs.register("test.dedupe2")
        def _dedupe2(_context, _params, _settings):
            release.wait(timeout=3)
            return {}

        first = jobs.submit(db, "test.dedupe2", {"period": "CY2024"}, settings=settings)
        second = jobs.submit(db, "test.dedupe2", {"period": "CY2023"}, settings=settings)
        assert first.id != second.id
        release.set()

    def test_dedupe_can_be_turned_off(self, runner):
        db, settings = runner

        @jobs.register("test.dedupe3")
        def _dedupe3(_context, _params, _settings):
            return {}

        first = jobs.submit(db, "test.dedupe3", {}, settings=settings, dedupe=False)
        second = jobs.submit(db, "test.dedupe3", {}, settings=settings, dedupe=False)
        assert first.id != second.id


class TestReaper:
    def test_a_job_with_a_dead_heartbeat_is_failed(self, db_session):
        db, _engine = db_session
        settings = Settings(_env_file=None, job_heartbeat_timeout_seconds=0.05)
        stale = Job(
            id=uuid.uuid4(),
            kind="test.orphan",
            state=JobState.RUNNING.value,
            params={},
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(stale)
        db.commit()

        assert jobs._reap_orphans(settings, reason="the worker process restarted") == 1
        db.expire_all()
        row = db.get(Job, stale.id)
        assert row.state == JobState.FAILED.value
        assert "reaped" in row.error

    def test_a_fresh_heartbeat_is_left_alone(self, db_session):
        db, _engine = db_session
        settings = Settings(_env_file=None, job_heartbeat_timeout_seconds=300)
        alive = Job(
            id=uuid.uuid4(),
            kind="test.alive",
            state=JobState.RUNNING.value,
            params={},
            started_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
        )
        db.add(alive)
        db.commit()
        assert jobs._reap_orphans(settings, reason="x") == 0
        db.expire_all()
        assert db.get(Job, alive.id).state == JobState.RUNNING.value

    def test_finished_jobs_are_never_reaped(self, db_session):
        db, _engine = db_session
        settings = Settings(_env_file=None, job_heartbeat_timeout_seconds=0.01)
        done = Job(
            id=uuid.uuid4(),
            kind="test.done",
            state=JobState.SUCCEEDED.value,
            params={},
            finished_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(done)
        db.commit()
        assert jobs._reap_orphans(settings, reason="x") == 0


class TestRetention:
    def test_old_finished_jobs_are_purged(self, db_session):
        db, _engine = db_session
        old = Job(
            id=uuid.uuid4(),
            kind="k",
            state=JobState.SUCCEEDED.value,
            params={},
            finished_at=datetime.now(timezone.utc) - timedelta(days=90),
        )
        recent = Job(
            id=uuid.uuid4(),
            kind="k",
            state=JobState.SUCCEEDED.value,
            params={},
            finished_at=datetime.now(timezone.utc),
        )
        running = Job(id=uuid.uuid4(), kind="k", state=JobState.RUNNING.value, params={})
        db.add_all([old, recent, running])
        db.commit()

        assert jobs.purge_old(db, older_than_days=30) == 1
        assert db.get(Job, old.id) is None
        assert db.get(Job, recent.id) is not None
        assert db.get(Job, running.id) is not None


class TestNoRunner:
    def test_submitting_without_a_runner_leaves_the_row_queued(self, db_session):
        db, _engine = db_session
        jobs.shutdown_runner(wait=False)

        @jobs.register("test.norunner")
        def _norunner(_context, _params, _settings):
            return {}

        row = jobs.submit(
            db, "test.norunner", {}, settings=Settings(_env_file=None), dedupe=False
        )
        # Honest: the row says QUEUED because nothing ran it, rather than
        # claiming a success that never happened.
        assert row.state == JobState.QUEUED.value
