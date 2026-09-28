"""Orchestration between the ORM and the pure engines.

The engines in this package take dicts and return dataclasses. They never touch
a database session, which is what lets the whole test suite run against them
directly with no container up. This module is the only place that knows about
both sides: it flattens ORM rows into plain dicts, calls the engines, and writes
the results back.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import MarginBasis
from sqlalchemy import select

from app.models import (
    AllocationRun,
    Company,
    Competitor,
    MarketAttractiveness,
    PortersAnalysis,
    Portfolio,
    PricingRecommendation,
    Scenario,
    StrategyReport,
    SwotAnalysis,
    UncertaintyAnalysis,
)
from app.db import queries
from app.services import market_structure, report_generator
from app.services.attractiveness_matrix import AttractivenessResult, run_attractiveness_matrix
from app.services.pricing_engine import PricingResult, run_pricing_engine
from app.services.swot_engine import SwotResult, run_swot_analysis

logger = logging.getLogger(__name__)


def competitor_payload(competitor: Competitor) -> dict[str, Any]:
    return {
        "competitor_name": competitor.competitor_name,
        "price_point": competitor.price_point,
        "market_share_pct": competitor.market_share_pct,
        "feature_scores": competitor.feature_scores or {},
        "financial_data": competitor.financial_data or {},
    }


def _market_structure_for(company: Company, settings: Settings):
    financials = company.financial_data or {}
    market = company.market_data or {}
    return market_structure.assess_market_structure(
        company_market_share_pct=financials.get("market_share_pct"),
        competitors=[competitor_payload(c) for c in company.competitors],
        analyst_intensity_override=market.get("competitive_intensity_score"),
        settings=settings,
    )


def run_swot(db: Session, company: Company, settings: Settings) -> SwotAnalysis:
    concentration = _market_structure_for(company, settings)
    result = run_swot_analysis(
        financial_data=company.financial_data or {},
        market_data=company.market_data or {},
        qualitative_inputs=company.qualitative_inputs or [],
        competitors=[competitor_payload(c) for c in company.competitors],
        industry=company.industry,
        concentration=concentration,
        settings=settings,
    )

    row = SwotAnalysis(
        company_id=company.id,
        strengths=[f.to_dict() for f in result.strengths],
        weaknesses=[f.to_dict() for f in result.weaknesses],
        opportunities=[f.to_dict() for f in result.opportunities],
        threats=[f.to_dict() for f in result.threats],
        calculation_basis=result.calculation_basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def swot_result_from_row(row: SwotAnalysis) -> SwotResult:
    """Rehydrate a stored SWOT row into the dataclass the engines expect.

    Reading the stored row rather than recomputing is deliberate: the matrix
    must be built on the exact grid that was persisted and shown to the user,
    not on a second analysis that may have drifted if inputs changed in between.
    """
    from app.enums import SwotCategory
    from app.services.swot_engine import SwotFactor

    def rebuild(items: list, category: SwotCategory) -> list[SwotFactor]:
        rebuilt: list[SwotFactor] = []
        for item in items or []:
            rebuilt.append(
                SwotFactor(
                    factor=str(item.get("factor", "")),
                    category=category,
                    evidence=str(item.get("evidence", "")),
                    impact_score=int(item.get("impact_score", 3)),
                    source=str(item.get("source", "unknown")),
                    metric=item.get("metric"),
                    benchmark_basis=item.get("benchmark_basis"),
                )
            )
        return rebuilt

    return SwotResult(
        strengths=rebuild(row.strengths, SwotCategory.STRENGTH),
        weaknesses=rebuild(row.weaknesses, SwotCategory.WEAKNESS),
        opportunities=rebuild(row.opportunities, SwotCategory.OPPORTUNITY),
        threats=rebuild(row.threats, SwotCategory.THREAT),
        calculation_basis=row.calculation_basis or {},
    )


def run_attractiveness(
    db: Session, company: Company, swot_row: SwotAnalysis, settings: Settings
) -> MarketAttractiveness:
    concentration = _market_structure_for(company, settings)
    result: AttractivenessResult = run_attractiveness_matrix(
        market_data=company.market_data or {},
        swot=swot_result_from_row(swot_row),
        competitive_intensity_score=concentration.competitive_intensity_score,
        settings=settings,
    )

    basis = dict(result.calculation_basis)
    basis["market_structure"] = concentration.basis

    row = MarketAttractiveness(
        company_id=company.id,
        swot_analysis_id=swot_row.id,
        market_growth_score=result.market_growth_score,
        market_size_score=result.market_size_score,
        profitability_score=result.profitability_score,
        competitive_intensity_score=result.competitive_intensity_score,
        overall_attractiveness_score=result.overall_attractiveness_score,
        competitive_strength_score=result.competitive_strength_score,
        quadrant=result.quadrant.value,
        borderline=result.borderline,
        calculation_basis=basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def run_pricing(
    db: Session,
    company: Company,
    *,
    cost_base: float,
    target_margin_pct: float,
    margin_basis: MarginBasis,
    settings: Settings,
) -> PricingRecommendation:
    result: PricingResult = run_pricing_engine(
        cost_base=cost_base,
        target_margin_pct=target_margin_pct,
        margin_basis=margin_basis,
        competitors=[competitor_payload(c) for c in company.competitors],
        company_feature_scores=company.feature_scores or {},
        settings=settings,
    )

    row = PricingRecommendation(
        company_id=company.id,
        cost_base=result.cost_base,
        competitor_avg_price=result.competitor_avg_price,
        target_margin_pct=result.target_margin_pct,
        margin_basis=result.margin_basis.value,
        recommended_price_range=result.recommended_price_range,
        reasoning=result.reasoning,
        calculation_basis=result.calculation_basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _pricing_result_from_row(row: PricingRecommendation) -> PricingResult:
    basis = row.calculation_basis or {}
    return PricingResult(
        cost_base=row.cost_base,
        target_margin_pct=row.target_margin_pct,
        margin_basis=MarginBasis(row.margin_basis),
        cost_plus_price=float(basis.get("cost_plus_anchor", 0.0)),
        competitor_avg_price=row.competitor_avg_price,
        value_adjustment_factor=float(
            (basis.get("value_adjustment") or {}).get("value_adjustment_factor", 1.0)
        ),
        recommended_price=float(row.recommended_price_range.get("optimal", 0.0)),
        recommended_price_range=row.recommended_price_range,
        implied_margin_pct=float(basis.get("implied_margin_pct", 0.0)),
        confidence=str((row.reasoning or {}).get("confidence", "UNKNOWN")),
        reasoning=row.reasoning or {},
        calculation_basis=basis,
    )


def _attractiveness_result_from_row(row: MarketAttractiveness) -> AttractivenessResult:
    from app.enums import Quadrant

    return AttractivenessResult(
        market_growth_score=row.market_growth_score,
        market_size_score=row.market_size_score,
        profitability_score=row.profitability_score,
        competitive_intensity_score=row.competitive_intensity_score,
        overall_attractiveness_score=row.overall_attractiveness_score,
        competitive_strength_score=row.competitive_strength_score,
        quadrant=Quadrant(row.quadrant),
        borderline=row.borderline,
        calculation_basis=row.calculation_basis or {},
    )


def run_report(db: Session, company: Company, settings: Settings) -> StrategyReport:
    """Build the structured context, then narrate it. Never raises for LLM problems."""
    # Three targeted LIMIT 1 reads rather than three full collection loads.
    # A company that has been re-run twenty times used to materialise sixty
    # rows here, each carrying a kilobyte-scale calculation_basis, to use three.
    swot_row = queries.latest_swot(db, company.id)
    attractiveness_row = queries.latest_matrix(db, company.id)
    pricing_row = queries.latest_pricing(db, company.id)

    context = report_generator.build_structured_context(
        company_id=str(company.id),
        company_name=company.name,
        industry=company.industry,
        data_source=company.data_source,
        swot=swot_result_from_row(swot_row),
        attractiveness=_attractiveness_result_from_row(attractiveness_row),
        pricing=_pricing_result_from_row(pricing_row) if pricing_row else None,
    )

    narrative = report_generator.generate_narrative(context, settings)

    row = StrategyReport(
        company_id=company.id,
        structured_context=context,
        ai_narrative=narrative,
        narrative_source=narrative.get("generated_by"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------
# V2
# --------------------------------------------------------------------------


def run_porters(db: Session, company: Company, settings: Settings) -> PortersAnalysis:
    from app.services.porters_engine import run_porters_analysis

    concentration = _market_structure_for(company, settings)
    result = run_porters_analysis(
        financial_data=company.financial_data or {},
        market_data=company.market_data or {},
        concentration=concentration,
        settings=settings,
    )

    basis = dict(result.calculation_basis)
    basis["market_structure"] = concentration.basis

    row = PortersAnalysis(
        company_id=company.id,
        forces=[f.to_dict() for f in result.forces],
        composite_score=result.composite_score,
        industry_attractiveness=(
            result.industry_attractiveness.value if result.industry_attractiveness else None
        ),
        forces_scored=result.forces_scored,
        calculation_basis=basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def compute_sensitivity(db: Session, company: Company, settings: Settings) -> dict:
    """Sensitivity over the latest stored matrix result.

    Reads the persisted row rather than recomputing, for the same reason the
    report generator does: the analysis must describe the placement the user is
    looking at, not a fresh one that may have drifted.
    """
    from app.services.sensitivity import run_sensitivity_analysis

    row = queries.latest_matrix(db, company.id)
    result = run_sensitivity_analysis(
        market_growth_score=row.market_growth_score,
        market_size_score=row.market_size_score,
        profitability_score=row.profitability_score,
        competitive_intensity_score=row.competitive_intensity_score,
        attractiveness=row.overall_attractiveness_score,
        strength=row.competitive_strength_score,
        settings=settings,
    )
    return {
        "company_id": str(company.id),
        "market_attractiveness_id": str(row.id),
        "baseline_quadrant": result.baseline_quadrant.value,
        "baseline_attractiveness": result.baseline_attractiveness,
        "baseline_strength": result.baseline_strength,
        "verdict": result.verdict.value,
        "axes": [a.to_dict() for a in result.axes],
        "strength_sensitivity": (
            result.strength_sensitivity.to_dict() if result.strength_sensitivity else None
        ),
        "binding_constraint": (
            result.binding_constraint.to_dict() if result.binding_constraint else None
        ),
        "calculation_basis": result.calculation_basis,
    }


def run_scenario_for(
    db: Session,
    company: Company,
    *,
    name: str,
    description: str | None,
    overrides: dict,
    settings: Settings,
) -> Scenario:
    from app.services import scenario_engine

    baseline_row = queries.latest_matrix(db, company.id)
    baseline_snapshot = {
        "market_growth_score": baseline_row.market_growth_score,
        "market_size_score": baseline_row.market_size_score,
        "profitability_score": baseline_row.profitability_score,
        "competitive_intensity_score": baseline_row.competitive_intensity_score,
        "overall_attractiveness_score": baseline_row.overall_attractiveness_score,
        "competitive_strength_score": baseline_row.competitive_strength_score,
        "quadrant": baseline_row.quadrant,
        "borderline": baseline_row.borderline,
    }

    result = scenario_engine.run_scenario(
        baseline_financial_data=company.financial_data or {},
        baseline_market_data=company.market_data or {},
        baseline_qualitative_inputs=company.qualitative_inputs or [],
        baseline_competitors=[competitor_payload(c) for c in company.competitors],
        baseline_snapshot=baseline_snapshot,
        industry=company.industry,
        overrides=overrides,
        settings=settings,
    )

    snapshot = scenario_engine.result_snapshot(result.attractiveness)
    row = Scenario(
        company_id=company.id,
        name=name,
        description=description,
        overrides=result.applied_overrides,
        baseline_snapshot=baseline_snapshot,
        scenario_result={
            **snapshot,
            "resulting_inputs": result.resulting_inputs,
            "warnings": result.warnings,
            "calculation_basis": result.attractiveness.calculation_basis,
            "narrative": scenario_engine.describe_move(
                baseline_snapshot["quadrant"], snapshot["quadrant"]
            ),
        },
        delta=result.delta,
        quadrant_changed=result.quadrant_changed,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def build_entity_timeline(db: Session, entity_key: str, settings: Settings) -> dict:
    from app.services.timeline import build_timeline

    companies = queries.companies_for_entity(db, entity_key)
    # One windowed query for every period's latest matrix row, instead of one
    # full-collection load per company inside the loop. This was the clearest
    # N+1 in the codebase: a ten-period entity issued eleven queries and
    # materialised every matrix row it had ever stored.
    latest_by_company = queries.latest_for_many(
        db, MarketAttractiveness, [c.id for c in companies]
    )
    rows: list[dict] = []
    for company in companies:
        latest = latest_by_company.get(company.id)
        rows.append(
            {
                "company_id": str(company.id),
                "period_label": company.period_label,
                "period_end": company.period_end,
                "attractiveness": latest.overall_attractiveness_score if latest else None,
                "strength": latest.competitive_strength_score if latest else None,
                "quadrant": latest.quadrant if latest else None,
                "borderline": latest.borderline if latest else False,
                "data_source": company.data_source,
            }
        )

    result = build_timeline(entity_key=entity_key, rows=rows, settings=settings)
    return {
        "entity_key": result.entity_key,
        "points": [p.to_dict() for p in result.points],
        "excluded": result.excluded,
        "attractiveness_trend": result.attractiveness_trend.value,
        "strength_trend": result.strength_trend.value,
        "quadrant_changes": result.quadrant_changes,
        "summary": result.summary,
        "calculation_basis": result.calculation_basis,
    }


# --------------------------------------------------------------------------
# V3
# --------------------------------------------------------------------------


def run_uncertainty(
    db: Session,
    company: Company,
    settings: Settings,
    *,
    overrides: dict | None = None,
    persist_inputs: bool = False,
) -> UncertaintyAnalysis:
    """Monte Carlo over the latest stored matrix result.

    Reads the persisted matrix row rather than recomputing, for the same reason
    the report generator and the sensitivity analysis do: the probabilities
    must describe the placement the user is looking at.
    """
    from app.services.uncertainty import run_uncertainty_analysis

    row = queries.latest_matrix(db, company.id)
    inputs = overrides if overrides is not None else (company.uncertainty_inputs or {})

    result = run_uncertainty_analysis(
        market_data=company.market_data or {},
        uncertainty_inputs=inputs,
        competitive_intensity_score=row.competitive_intensity_score,
        competitive_strength_score=row.competitive_strength_score,
        point_attractiveness=row.overall_attractiveness_score,
        point_strength=row.competitive_strength_score,
        point_quadrant=row.quadrant,
        settings=settings,
    )

    if persist_inputs and overrides is not None:
        company.uncertainty_inputs = overrides
        db.add(company)

    stored = UncertaintyAnalysis(
        company_id=company.id,
        market_attractiveness_id=row.id,
        point_quadrant=result.point_verdict,
        modal_quadrant=result.modal_quadrant,
        quadrant_probabilities=result.quadrant_probabilities,
        attractiveness_ci_90=result.attractiveness_ci,
        strength_ci_90=result.strength_ci,
        entropy_bits=result.entropy_bits,
        verdict_stability=result.verdict_stability.value,
        draws=result.draws,
        seed=result.seed,
        calculation_basis=result.calculation_basis,
    )
    db.add(stored)
    db.commit()
    db.refresh(stored)
    return stored


def portfolio_units(db: Session, portfolio: Portfolio) -> tuple[list, list[str]]:
    """Flatten members into engine units, reporting the ones that cannot play.

    A member whose company has never been through the matrix has no position on
    the grid, so it cannot be ranked. It is excluded and named rather than
    given a neutral position, which would put an unscored unit ahead of a
    genuinely weak one.
    """
    from app.services.portfolio import PortfolioUnit

    units: list[PortfolioUnit] = []
    unscored: list[str] = []

    # Two windowed queries for the whole portfolio. The previous version was an
    # N+1 twice over - a matrix collection load AND an uncertainty collection
    # load per member - so a twelve-unit portfolio issued twenty-five queries
    # to build twelve rows.
    company_ids = [m.company_id for m in portfolio.members]
    matrices = queries.latest_for_many(db, MarketAttractiveness, company_ids)
    entropies = queries.latest_for_many(db, UncertaintyAnalysis, company_ids)

    for member in portfolio.members:
        company = member.company
        matrix = matrices.get(member.company_id)
        if company is None or matrix is None:
            unscored.append(company.name if company else str(member.company_id))
            continue
        uncertainty = entropies.get(member.company_id)
        entropy = uncertainty.entropy_bits if uncertainty is not None else None
        units.append(
            PortfolioUnit(
                entity_key=company.entity_key or str(company.id),
                company_id=str(company.id),
                name=company.name,
                attractiveness=matrix.overall_attractiveness_score,
                strength=matrix.competitive_strength_score,
                quadrant=matrix.quadrant,
                capital_requested=member.capital_requested,
                capital_floor=member.capital_floor,
                revenue=member.revenue,
                period_label=company.period_label,
                entropy_bits=entropy,
            )
        )
    return units, unscored


def run_allocation(
    db: Session, portfolio: Portfolio, settings: Settings, *, budget: float | None = None
) -> AllocationRun:
    """Allocate a budget across the portfolio and store the run."""
    from app.services.portfolio import PortfolioInputError, allocate_capital

    units, unscored = portfolio_units(db, portfolio)
    if unscored:
        raise PortfolioInputError(
            f"{len(unscored)} member(s) have no market attractiveness result: "
            f"{', '.join(sorted(unscored))}. Run the matrix for each member first - "
            "an unscored unit has no position to rank, and giving it a neutral one "
            "would place it above units that were measured and came out weak."
        )

    effective_budget = portfolio.budget if budget is None else budget
    result = allocate_capital(units, budget=effective_budget, settings=settings)

    basis = dict(result.calculation_basis)
    basis["pool"] = {
        "budget": result.budget,
        "harvest_contribution": result.harvest_contribution,
        "pool": result.pool,
        "floors_total": result.floors_total,
        "discretionary_available": result.discretionary_available,
        "discretionary_allocated": result.discretionary_allocated,
        "unallocated": result.unallocated,
    }
    basis["warnings"] = result.warnings

    row = AllocationRun(
        portfolio_id=portfolio.id,
        budget=result.budget,
        allocations=[a.to_dict() for a in result.allocations],
        unfunded=result.unfunded,
        marginal_unit=result.marginal_unit,
        harvest_contribution=result.harvest_contribution,
        calculation_basis=basis,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
