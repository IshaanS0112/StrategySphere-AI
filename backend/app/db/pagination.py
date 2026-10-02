"""Keyset pagination over ``(created_at, id)``."""

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
    """Return ``(items, next_cursor, total)`` for a newest-first listing."""
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
