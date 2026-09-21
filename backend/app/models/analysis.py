"""Result tables for the four analysis stages.

Every one of these rows stores a ``calculation_basis`` blob alongside the
headline number. That blob holds the inputs, the weights, and the intermediate
terms that produced the score, so any figure the API returns can be recomputed
by hand from the row that contains it. It is the difference between a score and
a claim.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class SwotAnalysis(Base):
    __tablename__ = "swot_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Each list holds [{factor, evidence, impact_score, source, metric}] -
    # ``source`` distinguishes a computed financial comparison from an
    # analyst-supplied qualitative judgement.
    strengths: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    weaknesses: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    opportunities: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    threats: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="swot_analyses")


class MarketAttractiveness(Base):
    __tablename__ = "market_attractiveness"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    swot_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("swot_analyses.id", ondelete="SET NULL")
    )

    market_growth_score: Mapped[float] = mapped_column(Float, nullable=False)
    market_size_score: Mapped[float] = mapped_column(Float, nullable=False)
    profitability_score: Mapped[float] = mapped_column(Float, nullable=False)
    # 1-5, higher = more intense rivalry = worse for the company. Inverted in
    # the weighted sum, not negated, so the axis stays on a 1-5 scale.
    competitive_intensity_score: Mapped[float] = mapped_column(Float, nullable=False)

    overall_attractiveness_score: Mapped[float] = mapped_column(Float, nullable=False)
    competitive_strength_score: Mapped[float] = mapped_column(Float, nullable=False)

    quadrant: Mapped[str] = mapped_column(String(30), nullable=False)
    # True when the point sits within quadrant_borderline_margin of a boundary.
    # A 3.51 and a 3.49 should not be reported with the same confidence.
    borderline: Mapped[bool] = mapped_column(default=False, nullable=False)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="attractiveness_results")


class PricingRecommendation(Base):
    __tablename__ = "pricing_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cost_base: Mapped[float] = mapped_column(Float, nullable=False)
    competitor_avg_price: Mapped[float | None] = mapped_column(Float)
    target_margin_pct: Mapped[float] = mapped_column(Float, nullable=False)
    margin_basis: Mapped[str] = mapped_column(String(10), nullable=False)

    # {min, optimal, max}
    recommended_price_range: Mapped[dict] = mapped_column(JsonBlob, nullable=False)
    # Human-readable derivation plus every intermediate term.
    reasoning: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="pricing_recommendations")


class StrategyReport(Base):
    __tablename__ = "strategy_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Frozen before any model call. Everything the narrative is allowed to say
    # is in here, which is what makes the "the AI does not decide the strategy"
    # claim checkable rather than asserted.
    structured_context: Mapped[dict] = mapped_column(JsonBlob, nullable=False)
    ai_narrative: Mapped[dict | None] = mapped_column(JsonBlob)
    narrative_source: Mapped[str | None] = mapped_column(String(20))  # llm | template_fallback

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="reports")


# --------------------------------------------------------------------------
# V2
# --------------------------------------------------------------------------


class PortersAnalysis(Base):
    """Porter's Five Forces (Porter, 1979).

    Deliberately *not* collapsed into a single verdict column. Porter's point is
    that the five forces are read individually — an industry can be brutal on
    rivalry and comfortable on supplier power, and averaging that away destroys
    the only thing the framework is for. ``composite_score`` exists so the UI
    has one number to sort by, and it is labelled a project-defined composite
    everywhere it surfaces.
    """

    __tablename__ = "porters_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # [{force, score, source, evidence, inputs_used, inputs_missing}] - one per
    # force, including the ones that came back UNAVAILABLE.
    forces: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    # Mean of the forces that could be scored. Null when fewer than two were.
    composite_score: Mapped[float | None] = mapped_column(Float)
    industry_attractiveness: Mapped[str | None] = mapped_column(String(20))
    forces_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="porters_analyses")


class Scenario(Base):
    """A named set of input overrides and the result of recomputing under them.

    The overrides are stored rather than the mutated inputs, so a scenario is
    always readable as a delta from the baseline it was run against. Running a
    scenario never touches the company row — the pipeline operates on a copy.
    """

    __tablename__ = "scenarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))

    # {"market_data": {...}, "financial_data": {...}, "competitors": [...]}
    overrides: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # The recomputed matrix result, and the field-by-field delta from baseline.
    baseline_snapshot: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    scenario_result: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    delta: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    quadrant_changed: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="scenarios")


# --------------------------------------------------------------------------
# V3
# --------------------------------------------------------------------------


class UncertaintyAnalysis(Base):
    """A Monte Carlo over analyst-stated input distributions.

    The point verdict is deliberately stored alongside the modal one. They
    disagree whenever the point estimate sits near a boundary that the sampled
    mass straddles, and that disagreement is a finding about the inputs rather
    than a conflict to resolve in favour of one of them.

    ``seed`` and ``draws`` are columns, not basis entries, because a stored
    probability is only quotable if the run that produced it can be repeated
    exactly.
    """

    __tablename__ = "uncertainty_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    market_attractiveness_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_attractiveness.id", ondelete="SET NULL")
    )

    point_quadrant: Mapped[str] = mapped_column(String(30), nullable=False)
    modal_quadrant: Mapped[str] = mapped_column(String(30), nullable=False)

    quadrant_probabilities: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    attractiveness_ci_90: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    strength_ci_90: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    # Shannon entropy over the three quadrant probabilities, in bits.
    entropy_bits: Mapped[float] = mapped_column(Float, nullable=False)
    verdict_stability: Mapped[str] = mapped_column(String(20), nullable=False)

    draws: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="uncertainty_analyses")
