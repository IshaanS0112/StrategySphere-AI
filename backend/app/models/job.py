"""The jobs table: one row per unit of background work."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, JsonBlob, utc_now


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # A registered kind string, e.g. "benchmarks.build". Stable across deploys,
    # because a stored row has to stay readable after the code moves on.
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    params: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JsonBlob)
    error: Mapped[str | None] = mapped_column(String(2000))

    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str | None] = mapped_column(String(500))

    # Written as the job works. A row whose heartbeat has gone stale is reaped,
    # so a crashed worker cannot leave a job RUNNING for ever.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The id of the request that enqueued it, so a job's logs can be joined to
    # the API call that asked for it.
    request_id: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
