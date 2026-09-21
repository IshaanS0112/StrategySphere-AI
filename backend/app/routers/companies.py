from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.models import Company, Competitor
from app.routers.deps import CurrentCompany, DbSession
from app.schemas import CompanyCreate, CompanyOut, CompetitorCreate, CompetitorOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies(db: DbSession):
    return list(db.scalars(select(Company).order_by(Company.created_at.desc())))


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
