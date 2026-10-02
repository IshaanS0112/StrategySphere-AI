"""Job submission and polling."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app import errors
from app.enums import JobState
from app.models import Job
from app.routers.deps import AppSettings, DbSession
from app.schemas import BenchmarkBuildRequest, JobOut, PanelBuildRequest
from app.services import job_tasks, jobs

router = APIRouter(tags=["jobs"])


def _load(db, job_id: uuid.UUID) -> Job:
    row = db.get(Job, job_id)
    if row is None:
        raise errors.not_found("Job", job_id)
    return row


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: DbSession,
    kind: Annotated[str | None, Query(max_length=60)] = None,
    state: Annotated[JobState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if kind:
        statement = statement.where(Job.kind == kind)
    if state:
        statement = statement.where(Job.state == state.value)
    return list(db.scalars(statement))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DbSession, response: Response):
    row = _load(db, job_id)
    # Tell a polling client how long to wait. Without it every client invents
    # its own interval and the busiest one wins.
    if row.state in {JobState.QUEUED.value, JobState.RUNNING.value}:
        response.headers["Retry-After"] = "2"
    return row


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, db: DbSession):
    """Ask a running job to stop at its next checkpoint."""
    row = _load(db, job_id)
    if not jobs.cancel(db, job_id):
        raise errors.AppError(
            errors.JOB_CONFLICT,
            f"Job {job_id} is already {row.state} and cannot be cancelled.",
            state=row.state,
        )
    db.refresh(row)
    return row


@router.post(
    "/benchmarks/build",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["meta"],
)
def build_benchmarks(
    payload: BenchmarkBuildRequest,
    db: DbSession,
    settings: AppSettings,
    response: Response,
):
    """Rebuild the benchmark table from SEC filings, as a background job."""
    if not settings.edgar_user_agent:
        raise errors.AppError(
            errors.NOT_CONFIGURED,
            "EDGAR_USER_AGENT is not configured. SEC guidance requires automated "
            "access to data.sec.gov to declare a contact address, so this server "
            "will not start a build that cannot identify itself.",
        )

    row = jobs.submit(
        db,
        job_tasks.BENCHMARK_BUILD,
        payload.model_dump(exclude_none=True),
        settings=settings,
    )
    response.headers["Location"] = f"/jobs/{row.id}"
    return row


@router.post(
    "/validation/panels",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["strategy v2"],
)
def build_panel(
    payload: PanelBuildRequest, db: DbSession, settings: AppSettings, response: Response
):
    """Assemble a validation panel from filings, as a background job."""
    if not settings.edgar_user_agent:
        raise errors.AppError(
            errors.NOT_CONFIGURED,
            "EDGAR_USER_AGENT is not configured; a panel build cannot reach data.sec.gov.",
        )
    row = jobs.submit(
        db, job_tasks.PANEL_BUILD, payload.model_dump(exclude_none=True), settings=settings
    )
    response.headers["Location"] = f"/jobs/{row.id}"
    return row
