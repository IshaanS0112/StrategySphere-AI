"""Engine, session factory, and the dialect-portable JSON/UUID types."""

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Client-side timestamp default with microsecond precision."""
    return datetime.now(timezone.utc)


# Postgres is the deployment target and JSONB is what the schema in
# docs/architecture.md specifies.
JsonBlob = JSON().with_variant(JSONB(), "postgresql")


_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
