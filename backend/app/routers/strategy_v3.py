"""V3 endpoints: uncertainty, portfolios, and benchmark provenance.

Same discipline as V1 and V2. Anything that reads a prior stage reads the
**stored** row rather than recomputing, and an ordering violation is a 409 with
an explanation rather than a silent recompute behind the caller's back.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

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
from app.services.benchmarks import load_benchmark_table
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
    """Propagate stated input distributions through the matrix.

    With no distributions stated anywhere the run is still valid and returns a
    probability of 1.0 on the point verdict with zero entropy, which is the
    correct answer to "how uncertain is this" when nobody claimed to be
    uncertain about anything.
    """
    if not company.attractiveness_results:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NEEDS_MATRIX)

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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/companies/{company_id}/uncertainty", response_model=UncertaintyAnalysisOut)
def get_uncertainty_analysis(company: CurrentCompany):
    if not company.uncertainty_analyses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No uncertainty analysis has been run for this company yet.",
        )
    return company.uncertainty_analyses[-1]


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No such compan{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}",
        )

    seen: set[str] = set()
    for member in payload.members:
        key = str(member.company_id)
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Company {key} appears twice; a unit cannot compete against itself.",
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Portfolio {portfolio_id} not found"
        )
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
    """Run the budget-constrained allocation and store the result.

    A 409 rather than a partial plan when the floors cannot be met: a committee
    that asked whether this portfolio can be funded needs to hear that it
    cannot, not receive an allocation that quietly starves two units.
    """
    portfolio = _load_portfolio(db, portfolio_id)
    try:
        return analysis_pipeline.run_allocation(
            db, portfolio, settings, budget=payload.budget
        )
    except PortfolioInputError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/portfolios/{portfolio_id}/allocations", response_model=list[AllocationRunOut])
def list_allocations(portfolio_id: uuid.UUID, db: DbSession):
    return _load_portfolio(db, portfolio_id).allocation_runs


# --------------------------------------------------------------------------
# Benchmark provenance
# --------------------------------------------------------------------------

@router.get("/benchmarks/provenance", tags=["meta"])
def benchmark_provenance(settings: AppSettings):
    """What the live benchmark table is, and where every number in it came from.

    The single most useful endpoint for answering "are these benchmarks real".
    With no table configured it says so in the same words the built-in table has
    always used, which is the honest answer rather than an empty block.
    """
    table = load_benchmark_table(settings.industry_benchmarks_path)
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


@router.post("/benchmarks/build", tags=["meta"])
def build_benchmarks(settings: AppSettings):
    """Deliberately not implemented as a live fetch from a request handler.

    Building the table is a minutes-long job that makes hundreds of outbound
    requests to a public government API under a rate limit. Behind an
    unauthenticated HTTP endpoint that is a way for anyone who can reach this
    service to spend the operator's rate budget, and the operator would find
    out from the SEC rather than from their own logs. It is a CLI command,
    which is also where a long-running job belongs.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Benchmark building is a CLI job, not an HTTP endpoint. It makes "
            "hundreds of rate-limited requests to data.sec.gov over several "
            "minutes; exposing that on an unauthenticated route would let any "
            "caller spend the operator's SEC rate budget. Run:\n"
            "    EDGAR_USER_AGENT='Your Name you@example.com' \\\n"
            "    python backend/scripts/build_benchmarks.py --period CY2024 \\\n"
            "        --out data/benchmarks/edgar_CY2024.json\n"
            "then set INDUSTRY_BENCHMARKS_PATH to the output and restart. "
            "GET /benchmarks/provenance reports what is live now."
        ),
    )
