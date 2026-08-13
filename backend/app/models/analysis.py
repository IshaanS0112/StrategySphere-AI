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

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid, func
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
