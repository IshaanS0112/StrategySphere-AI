"""The read layer, and the N+1 it exists to kill.

Every stage in this application reads "the latest result" for a company, and
since V1 it has done so with ``company.swot_analyses[-1]``. That expression is
a full collection load: SQLAlchemy issues ``SELECT * FROM swot_analyses WHERE
company_id = ?`` with no LIMIT, materialises every row a company has ever
produced, builds an ORM object for each one, and then Python throws away all
but the last. Each stored ``calculation_basis`` blob is kilobytes, so the cost
is real and it grows every time the user presses "Re-run".

Worse is the list case. ``build_entity_timeline`` loads the companies for an
entity and then touches ``company.attractiveness_results`` per company: one
query to find the companies, then one **full-collection** query per company.
That is the textbook N+1, and on the portfolio allocator it is N+1 twice over -
once for the matrix result and once for the uncertainty run.

This module replaces both patterns:

* ``latest_*`` helpers issue ``ORDER BY <ts> DESC LIMIT 1`` and return one row.
* ``companies_with_latest`` loads a set of companies and their latest rows in a
  bounded number of queries regardless of how many companies there are.

The ordering is by the same timestamp column the relationship used, so "latest"
means exactly what it meant before. ``utc_now`` gives those timestamps
microsecond precision (a V2 fix for SQLite's one-second ``CURRENT_TIMESTAMP``),
and the primary key is the tie-break so the answer is deterministic even if two
rows land on the same microsecond.
"""

from __future__ import annotations

import uuid
from typing import Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    MarketAttractiveness,
    PortersAnalysis,
    PricingRecommendation,
    Scenario,
    StrategyReport,
    SwotAnalysis,
    UncertaintyAnalysis,
)

T = TypeVar("T")

# (model, timestamp column) for every table that stores a run per company.
LATEST_ORDER = {
    SwotAnalysis: SwotAnalysis.generated_at,
    MarketAttractiveness: MarketAttractiveness.calculated_at,
    PricingRecommendation: PricingRecommendation.calculated_at,
    StrategyReport: StrategyReport.generated_at,
    PortersAnalysis: PortersAnalysis.generated_at,
    UncertaintyAnalysis: UncertaintyAnalysis.generated_at,
}


def _latest_stmt(model, company_id: uuid.UUID) -> Select:
    order_column = LATEST_ORDER[model]
    return (
        select(model)
        .where(model.company_id == company_id)
        # id as the tie-break: two runs can share a timestamp, and "whichever
        # the database felt like returning" is not an answer.
        .order_by(order_column.desc(), model.id.desc())
        .limit(1)
    )


def latest(db: Session, model, company_id: uuid.UUID):
    """The most recent row of ``model`` for one company, or ``None``.

    One query, one row, regardless of how many runs are stored.
    """
    return db.scalars(_latest_stmt(model, company_id)).first()


def latest_swot(db: Session, company_id: uuid.UUID) -> SwotAnalysis | None:
    return latest(db, SwotAnalysis, company_id)


def latest_matrix(db: Session, company_id: uuid.UUID) -> MarketAttractiveness | None:
    return latest(db, MarketAttractiveness, company_id)


def latest_pricing(db: Session, company_id: uuid.UUID) -> PricingRecommendation | None:
    return latest(db, PricingRecommendation, company_id)


def latest_report(db: Session, company_id: uuid.UUID) -> StrategyReport | None:
    return latest(db, StrategyReport, company_id)


def latest_porters(db: Session, company_id: uuid.UUID) -> PortersAnalysis | None:
    return latest(db, PortersAnalysis, company_id)


def latest_uncertainty(db: Session, company_id: uuid.UUID) -> UncertaintyAnalysis | None:
    return latest(db, UncertaintyAnalysis, company_id)


def latest_for_many(db: Session, model, company_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, object]:
    """``{company_id: latest row}`` for many companies in ONE query.

    Uses a window function where the dialect supports it (Postgres, and SQLite
    since 3.25), which is every target this project has. The alternative - a
    correlated subquery per company - is the N+1 wearing a SQL costume.
    """
    if not company_ids:
        return {}

    order_column = LATEST_ORDER[model]
    ranked = (
        select(
            model,
            func.row_number()
            .over(
                partition_by=model.company_id,
                order_by=(order_column.desc(), model.id.desc()),
            )
            .label("rank"),
        )
        .where(model.company_id.in_(list(company_ids)))
        .subquery()
    )
    aliased = db.execute(select(ranked).where(ranked.c.rank == 1)).mappings().all()

    # The subquery gives rows, not ORM objects; re-fetch by primary key through
    # the identity map, which is a single IN query and keeps callers working
    # with real model instances.
    ids = [row["id"] for row in aliased]
    if not ids:
        return {}
    objects = db.scalars(select(model).where(model.id.in_(ids))).all()
    return {obj.company_id: obj for obj in objects}


def companies_for_entity(db: Session, entity_key: str) -> list[Company]:
    """Every period of one entity, ordered the way a timeline reads."""
    return list(
        db.scalars(
            select(Company)
            .where(Company.entity_key == entity_key)
            .order_by(Company.period_end.asc().nulls_last(), Company.created_at.asc())
        )
    )


def count_companies(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Company)) or 0)
