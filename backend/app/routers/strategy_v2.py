"""V2 endpoints: Porter's Five Forces, sensitivity, scenarios, timelines, validation.

Same discipline as V1's stages. Anything that reads a prior stage's result reads
the **stored** row rather than recomputing, so what the API returns is always
consistent with what the dashboard is already showing. Ordering violations are
409s with an explanation rather than a silent recompute.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, status
from sqlalchemy import select

from app.models import Company
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    PortersAnalysisOut,
    ScenarioCreate,
    ScenarioOut,
    ValidationRequest,
)
from app.services import analysis_pipeline
from app.services.scenario_engine import ScenarioInputError
from app.services.validation import ValidationInputError, run_validation

router = APIRouter(tags=["strategy v2"])

_NEEDS_MATRIX = (
    "Run the market attractiveness matrix first. This endpoint analyses a stored "
    "placement; without one there is nothing to analyse."
)


# --------------------------------------------------------------------------
# Porter's Five Forces
# --------------------------------------------------------------------------

@router.post("/companies/{company_id}/porters-analysis", response_model=PortersAnalysisOut)
def create_porters_analysis(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Score the five forces.

    Independent of the SWOT/matrix chain: Porter describes industry structure,
    not the firm's position within it, so it needs no upstream stage.
    """
    if not (company.market_data or company.financial_data or company.competitors):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No market data, financial data, or competitors supplied. All five "
                "forces would come back UNAVAILABLE, which is an honest output but "
                "not a useful one."
            ),
        )
    return analysis_pipeline.run_porters(db, company, settings)


@router.get("/companies/{company_id}/porters-analysis", response_model=PortersAnalysisOut)
def get_porters_analysis(company: CurrentCompany):
    if not company.porters_analyses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Porter's Five Forces analysis has been run for this company yet.",
        )
    return company.porters_analyses[-1]


# --------------------------------------------------------------------------
# Sensitivity
# --------------------------------------------------------------------------

@router.get("/companies/{company_id}/sensitivity")
def get_sensitivity(company: CurrentCompany, settings: AppSettings):
    """Exact minimum single-input change that would flip the quadrant.

    A GET rather than a POST: it derives from the stored matrix result and
    persists nothing, so it is safely repeatable and cacheable.
    """
    if not company.attractiveness_results:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NEEDS_MATRIX)
    return analysis_pipeline.compute_sensitivity(company, settings)


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

@router.post(
    "/companies/{company_id}/scenarios",
    response_model=ScenarioOut,
    status_code=status.HTTP_201_CREATED,
)
def create_scenario(
    company: CurrentCompany,
    payload: ScenarioCreate,
    db: DbSession,
    settings: AppSettings,
):
    """Recompute under overrides and store the delta from the current baseline."""
    if not company.attractiveness_results:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NEEDS_MATRIX)
    try:
        return analysis_pipeline.run_scenario_for(
            db,
            company,
            name=payload.name,
            description=payload.description,
            overrides=payload.overrides.model_dump(exclude_none=True),
            settings=settings,
        )
    except ScenarioInputError as exc:
        # A bad override is the caller's problem, not a server fault.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/companies/{company_id}/scenarios", response_model=list[ScenarioOut])
def list_scenarios(company: CurrentCompany):
    return company.scenarios


@router.delete(
    "/companies/{company_id}/scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_scenario(company: CurrentCompany, scenario_id: str, db: DbSession):
    match = [s for s in company.scenarios if str(s.id) == scenario_id]
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found."
        )
    db.delete(match[0])
    db.commit()


# --------------------------------------------------------------------------
# Multi-period timeline
# --------------------------------------------------------------------------

@router.get("/entities")
def list_entities(db: DbSession):
    """Entity keys with more than one period, i.e. the ones a timeline exists for."""
    rows = db.execute(
        select(Company.entity_key, Company.period_label, Company.name)
        .where(Company.entity_key.is_not(None))
        .order_by(Company.entity_key, Company.period_end)
    ).all()

    grouped: dict[str, dict] = {}
    for entity_key, period_label, name in rows:
        entry = grouped.setdefault(
            entity_key, {"entity_key": entity_key, "name": name, "periods": []}
        )
        entry["periods"].append(period_label)
    return list(grouped.values())


@router.get("/entities/{entity_key}/timeline")
def get_entity_timeline(
    entity_key: str = Path(pattern=r"^[a-z0-9][a-z0-9-]*$"),
    *,
    db: DbSession,
    settings: AppSettings,
):
    """Quadrant migration across the periods sharing this entity key."""
    exists = db.scalar(select(Company.id).where(Company.entity_key == entity_key))
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No company periods carry entity_key '{entity_key}'.",
        )
    return analysis_pipeline.build_entity_timeline(db, entity_key, settings)


# --------------------------------------------------------------------------
# Validation harness
# --------------------------------------------------------------------------

@router.post("/validation/backtest")
def run_backtest(payload: ValidationRequest, settings: AppSettings):
    """Score a labelled panel of companies against realised outcomes.

    Stateless by design: the panel is supplied in the request rather than read
    from the database, because validating the framework is a different activity
    from analysing a company and should not require loading one first.
    """
    from app.services.validation import PanelRow

    rows = [
        PanelRow(
            label=r.label or f"row-{i}",
            quadrant=r.quadrant,
            attractiveness=r.attractiveness,
            strength=r.strength,
            outcome=r.outcome,
        )
        for i, r in enumerate(payload.panel)
    ]
    try:
        result = run_validation(rows, settings)
    except ValidationInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return {
        "n": result.n,
        "by_quadrant": result.by_quadrant,
        "separation": result.separation,
        "spearman_rho": result.spearman_rho,
        "permutation_p_value": result.permutation_p_value,
        "permutations_run": result.permutations_run,
        "verdict": result.verdict,
        "calculation_basis": result.calculation_basis,
    }
