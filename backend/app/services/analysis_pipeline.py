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
    Company,
    Competitor,
    MarketAttractiveness,
    PortersAnalysis,
    PricingRecommendation,
    Scenario,
    StrategyReport,
    SwotAnalysis,
)
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
    swot_row = company.swot_analyses[-1]
    attractiveness_row = company.attractiveness_results[-1]
    pricing_row = company.pricing_recommendations[-1] if company.pricing_recommendations else None

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


def compute_sensitivity(company: Company, settings: Settings) -> dict:
    """Sensitivity over the latest stored matrix result.

    Reads the persisted row rather than recomputing, for the same reason the
    report generator does: the analysis must describe the placement the user is
    looking at, not a fresh one that may have drifted.
    """
    from app.services.sensitivity import run_sensitivity_analysis

    row = company.attractiveness_results[-1]
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

    baseline_row = company.attractiveness_results[-1]
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

    companies = list(
        db.scalars(select(Company).where(Company.entity_key == entity_key))
    )
    rows: list[dict] = []
    for company in companies:
        latest = company.attractiveness_results[-1] if company.attractiveness_results else None
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
