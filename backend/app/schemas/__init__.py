"""Request and response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import MarginBasis

ItemT = TypeVar("ItemT")

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


class PeriodFields(BaseModel):
    """Optional period identity. Absent means a standalone snapshot (V1 behaviour)."""

    entity_key: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description=(
            "Slug shared by every period of the same real company, e.g. "
            "'northwind-analytics'. Lowercase, digits and hyphens."
        ),
    )
    period_label: str | None = Field(default=None, max_length=40, examples=["FY2024"])
    period_end: date | None = Field(
        default=None,
        description=(
            "Period end date. Required for a company to appear in a timeline - "
            "labels cannot be sorted reliably."
        ),
    )

    @model_validator(mode="after")
    def _period_needs_a_date(self) -> "PeriodFields":
        if self.entity_key and self.period_end is None:
            raise ValueError(
                "entity_key was supplied without period_end. A period with no end "
                "date cannot be ordered against the others, so it would be silently "
                "dropped from the timeline."
            )
        return self


class ThreePointIn(BaseModel):
    """A low / mode / high estimate for one uncertain input."""

    low: float
    mode: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> "ThreePointIn":
        if self.low > self.high:
            raise ValueError(f"low {self.low} is above high {self.high}")
        if not self.low <= self.mode <= self.high:
            raise ValueError(
                f"mode {self.mode} sits outside [{self.low}, {self.high}]. Clamping it "
                "would sample a distribution you did not describe."
            )
        return self


class QualitativeFactorIn(BaseModel):
    factor: str = Field(min_length=1, max_length=200)
    category: Literal["STRENGTH", "WEAKNESS", "OPPORTUNITY", "THREAT"]
    evidence: str = Field(default="", max_length=2000)
    impact_score: int = Field(ge=1, le=5)


class CompanyCreate(PeriodFields):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    financial_data: dict[str, Any] = Field(default_factory=dict)
    market_data: dict[str, Any] = Field(default_factory=dict)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    qualitative_inputs: list[QualitativeFactorIn] = Field(default_factory=list)
    # Required, not optional: a case study with no provenance is not a case study.
    data_source: str = Field(min_length=3, max_length=500)
    # V3. {metric: {low, mode, high}} for the axis inputs the matrix reads.
    # Absent means no stated uncertainty, which is the V1/V2 behaviour exactly.
    uncertainty_inputs: dict[str, ThreePointIn] | None = None

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
    uncertainty_inputs: dict[str, Any] | None
    entity_key: str | None
    period_label: str | None
    period_end: date | None
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
    # Upper bound of 0.95 rather than 1.0: on MARGIN basis, cost / (1 - m) at m =
    # 0.99 returns 100x cost, which is arithmetically fine and commercially absurd.
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


# --------------------------------------------------------------------------
# V2 --------------------------------------------------------------------------


class PortersAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    forces: list[Any]
    composite_score: float | None
    industry_attractiveness: str | None
    forces_scored: int
    calculation_basis: dict[str, Any]
    generated_at: datetime | None


class CompetitorOverride(BaseModel):
    op: Literal["add", "remove", "update"]
    competitor_name: str | None = Field(default=None, max_length=200)
    price_point: float | None = Field(default=None, gt=0)
    market_share_pct: float | None = Field(default=None, ge=0, le=100)
    feature_scores: dict[str, float] = Field(default_factory=dict)
    financial_data: dict[str, Any] = Field(default_factory=dict)


class ScenarioOverrides(BaseModel):
    market_data: dict[str, Any] = Field(default_factory=dict)
    financial_data: dict[str, Any] = Field(default_factory=dict)
    competitors: list[CompetitorOverride] = Field(default_factory=list)


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    overrides: ScenarioOverrides


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    overrides: dict[str, Any]
    baseline_snapshot: dict[str, Any]
    scenario_result: dict[str, Any]
    delta: dict[str, Any]
    quadrant_changed: bool
    created_at: datetime | None


class ValidationRow(BaseModel):
    label: str = Field(default="", max_length=200)
    quadrant: Literal["INVEST_GROW", "SELECTIVE_INVEST", "HARVEST_DIVEST"]
    attractiveness: float = Field(ge=1, le=5)
    strength: float = Field(ge=1, le=5)
    outcome: float = Field(
        description="Realised outcome at T+n: revenue CAGR, TSR, margin change - any ordinal measure"
    )


class ValidationRequest(BaseModel):
    panel: list[ValidationRow] = Field(min_length=3)


# --------------------------------------------------------------------------
# V3 --------------------------------------------------------------------------


class UncertaintyRequest(BaseModel):
    """Optional per-run overrides for the stored distributions."""

    uncertainty_inputs: dict[str, ThreePointIn] | None = Field(
        default=None,
        description=(
            "Overrides the company's stored uncertainty_inputs for this run only. "
            "Omit to use what is stored."
        ),
    )
    persist_inputs: bool = Field(
        default=False,
        description="Also write these distributions back onto the company row.",
    )


class UncertaintyAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    market_attractiveness_id: uuid.UUID | None
    point_quadrant: str
    modal_quadrant: str
    quadrant_probabilities: dict[str, Any]
    attractiveness_ci_90: list[Any]
    strength_ci_90: list[Any]
    entropy_bits: float
    verdict_stability: str
    draws: int
    seed: int
    calculation_basis: dict[str, Any]
    generated_at: datetime | None


class PortfolioMemberCreate(BaseModel):
    company_id: uuid.UUID
    revenue: float | None = Field(
        default=None, ge=0, description="Bubble size, and the base of the harvest contribution"
    )
    capital_requested: float = Field(ge=0)
    capital_floor: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Minimum to keep the unit operating. Funded before anything "
            "discretionary, and part of capital_requested rather than on top of it."
        ),
    )

    @model_validator(mode="after")
    def _floor_within_request(self) -> "PortfolioMemberCreate":
        if self.capital_floor > self.capital_requested:
            raise ValueError(
                "capital_floor exceeds capital_requested. The floor is the "
                "non-discretionary part of the request, not an amount on top of it."
            )
        return self


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    budget: float = Field(ge=0)
    # Two, not one: GE-McKinsey is a comparison across units, and a portfolio of
    # one is the single-company view the rest of the application already gives.
    members: list[PortfolioMemberCreate] = Field(min_length=2)


class PortfolioMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    revenue: float | None
    capital_requested: float
    capital_floor: float


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    budget: float
    members: list[PortfolioMemberOut]
    created_at: datetime | None


class AllocationRequest(BaseModel):
    budget: float | None = Field(
        default=None,
        ge=0,
        description="Overrides the portfolio's stored budget for this run only.",
    )


class AllocationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    portfolio_id: uuid.UUID
    budget: float
    allocations: list[Any]
    unfunded: list[Any]
    marginal_unit: dict[str, Any] | None
    harvest_contribution: float
    calculation_basis: dict[str, Any]
    generated_at: datetime | None


# --------------------------------------------------------------------------
# V3.1 --------------------------------------------------------------------------


class Page(BaseModel, Generic[ItemT]):
    """A cursor-paginated slice."""

    items: list[ItemT]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque. Pass back as ?cursor= for the next page; null means the end.",
    )
    # Deliberately not a total count. COUNT(*) on every page is a full scan to
    # render a number nobody acts on; ask for it explicitly with ?with_total=1.
    total: int | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    state: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    progress: float
    message: str | None
    request_id: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None


class BenchmarkBuildRequest(BaseModel):
    period: str = Field(default="CY2024", pattern=r"^CY\d{4}$")
    prior_period: str | None = Field(default=None, pattern=r"^CY\d{4}$")
    out: str | None = Field(
        default=None,
        max_length=300,
        description="Where to write the table. Defaults to data/benchmarks/edgar_<period>.json",
    )
    min_sector_n: int | None = Field(default=None, ge=2, le=5000)
    sic_limit: int | None = Field(default=None, ge=0, le=10000)
    offline: bool = Field(
        default=False, description="Serve from the response cache only; fail on a miss."
    )

    @field_validator("out")
    @classmethod
    def _contained(cls, value: str | None) -> str | None:
        # A path this endpoint accepts becomes a file this server writes.
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned.startswith("/") or ".." in cleaned.split("/"):
            raise ValueError("out must be a relative path inside data/")
        if not cleaned.startswith("data/"):
            raise ValueError("out must live under data/")
        return cleaned


class PanelBuildRequest(BaseModel):
    scoring_period: str = Field(default="CY2020", pattern=r"^CY\d{4}$")
    horizon: int = Field(default=3, ge=1, le=10)
    out: str | None = Field(default=None, max_length=300)
    offline: bool = False
