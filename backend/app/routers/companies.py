"""Company and competitor CRUD, with keyset-paginated listing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select

from app import errors
from app.db.pagination import InvalidCursor, clamp_limit, paginate
from app.models import Company, Competitor
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    CompanyCreate,
    CompanyOut,
    CompetitorCreate,
    CompetitorOut,
    Page,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyOut])
def list_companies(
    db: DbSession,
    settings: AppSettings,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    industry: Annotated[str | None, Query(max_length=100)] = None,
    entity_key: Annotated[str | None, Query(max_length=120)] = None,
    q: Annotated[str | None, Query(max_length=200, description="Substring of the name")] = None,
    with_total: Annotated[bool, Query(description="Also run a COUNT. Costs a scan.")] = False,
):
    """Newest first, keyset-paginated, with filters the dashboard actually uses."""
    statement = select(Company)
    if industry:
        statement = statement.where(func.lower(Company.industry) == industry.strip().lower())
    if entity_key:
        statement = statement.where(Company.entity_key == entity_key)
    if q:
        # ILIKE on a name column with no trigram index is a scan.
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(func.lower(Company.name).like(needle), func.lower(Company.data_source).like(needle))
        )

    try:
        items, next_cursor, total = paginate(
            db,
            statement,
            model=Company,
            limit=clamp_limit(limit, settings.page_size_default, settings.page_size_max),
            cursor=cursor,
            with_total=with_total,
        )
    except InvalidCursor as exc:
        raise errors.invalid_input(str(exc)) from exc

    return Page[CompanyOut](items=items, next_cursor=next_cursor, total=total)


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: DbSession):
    company = Company(
        name=payload.name,
        industry=payload.industry,
        financial_data=payload.financial_data,
        market_data=payload.market_data,
        feature_scores=payload.feature_scores,
        qualitative_inputs=[factor.model_dump() for factor in payload.qualitative_inputs],
        data_source=payload.data_source,
        entity_key=payload.entity_key,
        period_label=payload.period_label,
        period_end=payload.period_end,
        uncertainty_inputs=(
            {key: value.model_dump() for key, value in payload.uncertainty_inputs.items()}
            if payload.uncertainty_inputs
            else None
        ),
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyOut)
def get_company_detail(company: CurrentCompany):
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company: CurrentCompany, db: DbSession):
    db.delete(company)
    db.commit()


@router.post(
    "/{company_id}/competitors",
    response_model=CompetitorOut,
    status_code=status.HTTP_201_CREATED,
    tags=["competitors"],
)
def add_competitor(company: CurrentCompany, payload: CompetitorCreate, db: DbSession):
    competitor = Competitor(company_id=company.id, **payload.model_dump())
    db.add(competitor)
    db.commit()
    db.refresh(competitor)
    return competitor


@router.get(
    "/{company_id}/competitors", response_model=list[CompetitorOut], tags=["competitors"]
)
def list_competitors(company: CurrentCompany):
    return company.competitors
