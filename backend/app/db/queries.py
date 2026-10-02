"""The read layer: latest-result lookups that read one row, not a collection."""

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
    """The most recent row of ``model`` for one company, or ``None``."""
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
    """``{company_id: latest row}`` for many companies in ONE query."""
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

    # The subquery gives rows, not ORM objects; re-fetch by primary key through the
    # identity map, which is a single IN query and keeps callers working with real
    # model instances.
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
