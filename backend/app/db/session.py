from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Client-side timestamp default with microsecond precision.

    Used instead of relying on the database's ``now()`` because SQLite's
    CURRENT_TIMESTAMP has one-second resolution. Two analyses run in the same
    second would tie, and the "latest result" lookups throughout the pipeline
    (``company.swot_analyses[-1]``) would return an arbitrary one of them.
    ``server_default`` is still declared so rows inserted outside the ORM are
    timestamped too.
    """
    return datetime.now(timezone.utc)


# Postgres is the deployment target and JSONB is what the schema in
# docs/architecture.md specifies. Declaring it as a variant keeps the same
# models loadable under SQLite, which is what lets the API integration tests
# run on a clone with no database container up.
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
