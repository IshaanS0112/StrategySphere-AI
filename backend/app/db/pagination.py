"""Keyset pagination over ``(created_at, id)``.

``GET /companies`` returned every row. That is fine for the three case studies
and wrong the moment someone loads a real book of business - the response grows
without bound, the JSON serialiser walks the whole table, and the dashboard
renders a list nobody scrolls.

**Keyset, not offset.** ``LIMIT n OFFSET m`` makes the database walk and throw
away m rows, so page 50 costs fifty times page 1, and any row inserted while a
client pages shifts every later page - duplicating one row and skipping
another. A cursor over a strictly-ordered key pair does neither: it is a
``WHERE (created_at, id) < (?, ?)`` seek that costs the same for every page and
is stable under concurrent writes.

The cursor is base64 over ``<iso timestamp>|<uuid>``. Opaque so clients do not
build on its shape, but decodable by a developer with a terminal, because an
undebuggable cursor is its own support ticket.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import Session


class InvalidCursor(ValueError):
    """The cursor did not come from this API, or was corrupted in transit."""


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        timestamp, _, identifier = raw.partition("|")
        return datetime.fromisoformat(timestamp), uuid.UUID(identifier)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor(
            f"cursor {cursor!r} is not one this API issued. Drop it and start "
            "from the first page rather than guessing at its contents."
        ) from exc


def paginate(
    db: Session,
    statement: Select,
    *,
    model,
    limit: int,
    cursor: str | None = None,
    with_total: bool = False,
) -> tuple[list[Any], str | None, int | None]:
    """Return ``(items, next_cursor, total)`` for a newest-first listing.

    Fetches ``limit + 1`` rows and discards the extra. That is how the
    existence of a next page is known without a second COUNT query - the
    sentinel row either exists or it does not.
    """
    from sqlalchemy import func, select

    ordered = statement.order_by(model.created_at.desc(), model.id.desc())

    if cursor:
        last_created, last_id = decode_cursor(cursor)
        ordered = ordered.where(
            or_(
                model.created_at < last_created,
                and_(model.created_at == last_created, model.id < last_id),
            )
        )

    rows = list(db.scalars(ordered.limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )

    total: int | None = None
    if with_total:
        # Only on request. A COUNT on every page is a full scan to render a
        # number almost no caller reads.
        count_statement = select(func.count()).select_from(statement.subquery())
        total = int(db.scalar(count_statement) or 0)

    return items, next_cursor, total


def clamp_limit(requested: int | None, default: int, maximum: int) -> int:
    """A client-supplied page size is an invitation to ask for the whole table."""
    if requested is None:
        return default
    return max(1, min(int(requested), maximum))
