"""The four analysis stages.

Each stage is a POST that computes and persists, plus a GET that returns the
latest stored result. Ordering is enforced with 409s rather than silently
recomputing an upstream stage: the matrix must be built on the SWOT grid the
user actually saw, and a hidden recompute is how a dashboard ends up showing a
quadrant that no longer matches the grid above it.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import errors
from app.db import queries
from app.enums import MarginBasis
from app.routers.deps import AppSettings, CurrentCompany, DbSession
from app.schemas import (
    MarketAttractivenessOut,
    PricingRecommendationOut,
    PricingRequest,
    StrategyReportOut,
    SwotAnalysisOut,
)
from app.services import analysis_pipeline
from app.services.pricing_engine import PricingInputError

router = APIRouter(prefix="/companies", tags=["analysis"])


@router.post("/{company_id}/swot-analysis", response_model=SwotAnalysisOut)
def create_swot_analysis(company: CurrentCompany, db: DbSession, settings: AppSettings):
    if not (company.financial_data or company.market_data or company.qualitative_inputs):
        raise errors.AppError(
            errors.INSUFFICIENT_INPUT,
            "This company has no financial data, market data, or qualitative inputs. "
            "A SWOT grid scored from nothing would be four empty lists presented as "
            "an analysis.",
        )
    return analysis_pipeline.run_swot(db, company, settings)


@router.get("/{company_id}/swot-analysis", response_model=SwotAnalysisOut)
def get_swot_analysis(company: CurrentCompany, db: DbSession):
    row = queries.latest_swot(db, company.id)
    if row is None:
        raise errors.AppError(
            errors.NOT_FOUND, "No SWOT analysis has been run for this company yet."
        )
    return row


@router.post("/{company_id}/market-attractiveness", response_model=MarketAttractivenessOut)
def create_market_attractiveness(company: CurrentCompany, db: DbSession, settings: AppSettings):
    swot_row = queries.latest_swot(db, company.id)
    if swot_row is None:
        raise errors.stage_order(
            "Run the SWOT analysis first. The competitive-strength axis is derived "
            "from the scored SWOT factors, so there is nothing to plot without it.",
            needs="swot",
        )
    return analysis_pipeline.run_attractiveness(db, company, swot_row, settings)


@router.get("/{company_id}/market-attractiveness", response_model=MarketAttractivenessOut)
def get_market_attractiveness(company: CurrentCompany, db: DbSession):
    row = queries.latest_matrix(db, company.id)
    if row is None:
        raise errors.AppError(
            errors.NOT_FOUND, "No market attractiveness result exists for this company yet."
        )
    return row


@router.post("/{company_id}/pricing-recommendation", response_model=PricingRecommendationOut)
def create_pricing_recommendation(
    company: CurrentCompany,
    payload: PricingRequest,
    db: DbSession,
    settings: AppSettings,
):
    basis = payload.margin_basis or MarginBasis(settings.pricing_default_margin_basis)
    try:
        return analysis_pipeline.run_pricing(
            db,
            company,
            cost_base=payload.cost_base,
            target_margin_pct=payload.target_margin_pct,
            margin_basis=basis,
            settings=settings,
        )
    except PricingInputError as exc:
        # A bad price input is the caller's problem, not a server fault.
        raise errors.invalid_input(str(exc)) from exc


@router.get("/{company_id}/pricing-recommendation", response_model=PricingRecommendationOut)
def get_pricing_recommendation(company: CurrentCompany, db: DbSession):
    row = queries.latest_pricing(db, company.id)
    if row is None:
        raise errors.AppError(
            errors.NOT_FOUND, "No pricing recommendation exists for this company yet."
        )
    return row


@router.post("/{company_id}/generate-strategy-report", response_model=StrategyReportOut)
def generate_strategy_report(company: CurrentCompany, db: DbSession, settings: AppSettings):
    """Narrate the stored structured context.

    Never returns 5xx for an LLM problem: if the model call fails, times out, or
    returns malformed JSON, the templated fallback is persisted instead and the
    response carries ``narrative_source = "template_fallback"``.
    """
    if queries.latest_swot(db, company.id) is None or queries.latest_matrix(db, company.id) is None:
        raise errors.stage_order(
            "Run the SWOT analysis and the market attractiveness matrix first. "
            "The report narrates computed scores; without them there is nothing "
            "to narrate and the model would be inventing the strategy.",
            needs="swot+matrix",
        )
    return analysis_pipeline.run_report(db, company, settings)


@router.get("/{company_id}/strategy-report", response_model=StrategyReportOut)
def get_strategy_report(company: CurrentCompany, db: DbSession):
    row = queries.latest_report(db, company.id)
    if row is None:
        raise errors.AppError(
            errors.NOT_FOUND, "No strategy report has been generated for this company yet."
        )
    return row
