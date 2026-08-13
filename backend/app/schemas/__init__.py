"""Request and response schemas.

Input validation is doing real work here, not ceremony. Market shares are
bounded to 0-100, impact scores to 1-5, and margins to a range that cannot make
the cost-plus formula divide by zero. Every one of those constraints exists
because the corresponding engine would otherwise produce a confident, wrong
number from a typo.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import MarginBasis

FEATURE_SCORE_MIN = 1.0
FEATURE_SCORE_MAX = 5.0


def _validate_feature_scores(scores: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for name, value in (scores or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"feature_scores['{name}'] must be a number")
        if not FEATURE_SCORE_MIN <= float(value) <= FEATURE_SCORE_MAX:
            raise ValueError(
                f"feature_scores['{name}'] = {value} is outside the 1-5 scale. The "
                "pricing engine's value adjustment assumes a shared 1-5 scale on both "
                "sides of the comparison."
            )
        cleaned[str(name)] = float(value)
    return cleaned


class QualitativeFactorIn(BaseModel):
    factor: str = Field(min_length=1, max_length=200)
    category: Literal["STRENGTH", "WEAKNESS", "OPPORTUNITY", "THREAT"]
    evidence: str = Field(default="", max_length=2000)
    impact_score: int = Field(ge=1, le=5)


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    financial_data: dict[str, Any] = Field(default_factory=dict)
    market_data: dict[str, Any] = Field(default_factory=dict)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    qualitative_inputs: list[QualitativeFactorIn] = Field(default_factory=list)
    # Required, not optional: a case study with no provenance is not a case study.
    data_source: str = Field(min_length=3, max_length=500)

    @field_validator("feature_scores")
    @classmethod
    def check_features(cls, value: dict[str, Any]) -> dict[str, float]:
        return _validate_feature_scores(value)

    @field_validator("financial_data")
    @classmethod
    def check_market_share(cls, value: dict[str, Any]) -> dict[str, Any]:
        share = value.get("market_share_pct")
        if isinstance(share, (int, float)) and not isinstance(share, bool):
            if not 0 <= float(share) <= 100:
                raise ValueError("financial_data.market_share_pct must be between 0 and 100")
        return value


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    financial_data: dict[str, Any]
    market_data: dict[str, Any]
    feature_scores: dict[str, Any]
    qualitative_inputs: list[Any]
    data_source: str | None
    created_at: datetime | None


class CompetitorCreate(BaseModel):
    competitor_name: str = Field(min_length=1, max_length=200)
    price_point: float | None = Field(default=None, gt=0)
    market_share_pct: float | None = Field(default=None, ge=0, le=100)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    financial_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feature_scores")
    @classmethod
    def check_features(cls, value: dict[str, Any]) -> dict[str, float]:
        return _validate_feature_scores(value)


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    competitor_name: str
    price_point: float | None
    market_share_pct: float | None
    feature_scores: dict[str, Any]
    financial_data: dict[str, Any]
    added_at: datetime | None


class SwotAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    strengths: list[Any]
    weaknesses: list[Any]
    opportunities: list[Any]
    threats: list[Any]
    calculation_basis: dict[str, Any]
    generated_at: datetime | None


class MarketAttractivenessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    market_growth_score: float
    market_size_score: float
    profitability_score: float
    competitive_intensity_score: float
    overall_attractiveness_score: float
    competitive_strength_score: float
    quadrant: str
    borderline: bool
    calculation_basis: dict[str, Any]
    calculated_at: datetime | None


class PricingRequest(BaseModel):
    cost_base: float = Field(gt=0, description="Unit cost in the same currency as competitor prices")
    # Upper bound of 0.95 rather than 1.0: on MARGIN basis, cost / (1 - m) at
    # m = 0.99 returns 100x cost, which is arithmetically fine and
    # commercially absurd. 0.95 is already a 20x multiple.
    target_margin_pct: float = Field(
        ge=0, le=0.95, description="Fraction, not percent: 0.40 means 40%"
    )
    margin_basis: MarginBasis | None = Field(
        default=None,
        description=(
            "MARGIN: price = cost / (1 - m), realised margin = m. "
            "MARKUP: price = cost x (1 + m), realised margin = m / (1 + m). "
            "Defaults to the configured basis (MARGIN)."
        ),
    )


class PricingRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    cost_base: float
    competitor_avg_price: float | None
    target_margin_pct: float
    margin_basis: str
    recommended_price_range: dict[str, Any]
    reasoning: dict[str, Any]
    calculation_basis: dict[str, Any]
    calculated_at: datetime | None


class StrategyReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    structured_context: dict[str, Any]
    ai_narrative: dict[str, Any] | None
    narrative_source: str | None
    generated_at: datetime | None
