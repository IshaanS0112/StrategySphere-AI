"""V3 endpoints: uncertainty, portfolios, and benchmark provenance."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app import errors
from app.db import queries
from app.models import Company, Portfolio, PortfolioMember
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    AllocationRequest,
    AllocationRunOut,
    PortfolioCreate,
    PortfolioOut,
    UncertaintyAnalysisOut,
    UncertaintyRequest,
)
from app.services import analysis_pipeline
from app.services import cache
from app.services.portfolio import PortfolioInputError
from app.services.uncertainty import UncertaintyInputError

router = APIRouter(tags=["strategy v3"])

_NEEDS_MATRIX = (
    "Run the market attractiveness matrix first. The Monte Carlo resamples a stored "
    "placement; without one there is nothing to propagate uncertainty through."
)


# --------------------------------------------------------------------------
# Uncertainty
# --------------------------------------------------------------------------

@router.post(
    "/companies/{company_id}/uncertainty",
    response_model=UncertaintyAnalysisOut,
    status_code=status.HTTP_201_CREATED,
)
def create_uncertainty_analysis(
    company: CurrentCompany,
    payload: UncertaintyRequest,
    db: DbSession,
    settings: AppSettings,
):
    """Propagate stated input distributions through the matrix."""
    if queries.latest_matrix(db, company.id) is None:
        raise errors.stage_order(_NEEDS_MATRIX, needs="matrix")

    overrides = (
        {key: value.model_dump() for key, value in payload.uncertainty_inputs.items()}
        if payload.uncertainty_inputs is not None
        else None
    )
    try:
        return analysis_pipeline.run_uncertainty(
            db,
            company,
            settings,
            overrides=overrides,
            persist_inputs=payload.persist_inputs,
        )
    except UncertaintyInputError as exc:
        raise errors.invalid_input(str(exc)) from exc


@router.get("/companies/{company_id}/uncertainty", response_model=UncertaintyAnalysisOut)
def get_uncertainty_analysis(company: CurrentCompany, db: DbSession):
    row = queries.latest_uncertainty(db, company.id)
    if row is None:
        raise errors.AppError(
            errors.NOT_FOUND, "No uncertainty analysis has been run for this company yet."
        )
    return row


# --------------------------------------------------------------------------
# Portfolios
# --------------------------------------------------------------------------

@router.post("/portfolios", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate, db: DbSession):
    """Create a named portfolio over existing company-period rows."""
    missing = [
        str(member.company_id)
        for member in payload.members
        if db.get(Company, member.company_id) is None
    ]
    if missing:
        raise errors.AppError(
            errors.NOT_FOUND,
            f"No such compan{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}",
            missing_company_ids=missing,
        )

    seen: set[str] = set()
    for member in payload.members:
        key = str(member.company_id)
        if key in seen:
            raise errors.invalid_input(
                f"Company {key} appears twice; a unit cannot compete against itself.",
                duplicate_company_id=key,
            )
        seen.add(key)

    portfolio = Portfolio(
        name=payload.name, description=payload.description, budget=payload.budget
    )
    portfolio.members = [
        PortfolioMember(
            company_id=member.company_id,
            revenue=member.revenue,
            capital_requested=member.capital_requested,
            capital_floor=member.capital_floor,
        )
        for member in payload.members
    ]
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.get("/portfolios", response_model=list[PortfolioOut])
def list_portfolios(db: DbSession):
    return list(db.scalars(select(Portfolio).order_by(Portfolio.created_at)))


def _load_portfolio(db, portfolio_id: uuid.UUID) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise errors.not_found("Portfolio", portfolio_id)
    return portfolio


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioOut)
def get_portfolio(portfolio_id: uuid.UUID, db: DbSession):
    return _load_portfolio(db, portfolio_id)


@router.delete("/portfolios/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(portfolio_id: uuid.UUID, db: DbSession):
    db.delete(_load_portfolio(db, portfolio_id))
    db.commit()


@router.post("/portfolios/{portfolio_id}/allocate", response_model=AllocationRunOut)
def allocate(
    portfolio_id: uuid.UUID,
    payload: AllocationRequest,
    db: DbSession,
    settings: AppSettings,
):
    """Run the budget-constrained allocation and store the result."""
    portfolio = _load_portfolio(db, portfolio_id)
    try:
        return analysis_pipeline.run_allocation(
            db, portfolio, settings, budget=payload.budget
        )
    except PortfolioInputError as exc:
        raise errors.AppError(errors.BUDGET_INFEASIBLE, str(exc)) from exc


@router.get("/portfolios/{portfolio_id}/allocations", response_model=list[AllocationRunOut])
def list_allocations(portfolio_id: uuid.UUID, db: DbSession):
    return _load_portfolio(db, portfolio_id).allocation_runs


# --------------------------------------------------------------------------
# Benchmark provenance
# --------------------------------------------------------------------------

@router.get("/benchmarks/provenance", tags=["meta"])
def benchmark_provenance(settings: AppSettings):
    """What the live benchmark table is, and where every number in it came from."""
    table = cache.benchmark_table(settings.industry_benchmarks_path)
    sectors = sorted(key for key in table.rows if key != "_default")
    return {
        "path": settings.industry_benchmarks_path or None,
        "provenance": table.provenance,
        "is_edgar_sourced": table.provenance_detail is not None,
        "sectors": sectors,
        "sector_count": len(sectors),
        "metrics_by_sector": {
            sector: sorted(row) for sector, row in sorted(table.rows.items())
        },
        "row_basis": table.row_basis,
        "sample_sizes": {
            sector: {metric: entry.get("n") for metric, entry in metrics.items()}
            for sector, metrics in sorted(table.meta.items())
        },
        "detail": table.provenance_detail,
        "how_to_rebuild": (
            "EDGAR_USER_AGENT='Your Name you@example.com' python "
            "backend/scripts/build_benchmarks.py --period CY2024 "
            "--out data/benchmarks/edgar_CY2024.json"
        ),
    }


# POST /benchmarks/build now lives in routers/jobs.py.
