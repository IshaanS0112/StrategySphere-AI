"""The company table: one row is a company as reported for one period."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.analysis import (
        MarketAttractiveness,
        PortersAnalysis,
        PricingRecommendation,
        Scenario,
        StrategyReport,
        SwotAnalysis,
        UncertaintyAnalysis,
    )
    from app.models.competitor import Competitor


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))

    # Free-shaped by design: different case studies disclose different line items.
    financial_data: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Market-level inputs (growth, size, regulatory outlook). Kept separate
    # from financial_data because they describe the market, not the firm.
    market_data: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # {feature_name: score} on a 1-5 scale, using the same feature names as the
    # competitors.
    feature_scores: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Analyst-supplied qualitative factors: brand, distribution, talent.
    qualitative_inputs: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)

    # Where the numbers came from. Required in the API layer; a case study with
    # no provenance is not a case study.
    data_source: Mapped[str | None] = mapped_column(String(500))

    # --- V2: the period dimension ------------------------------------------
    # A row in this table is a company *as reported for one period*, not a company.
    entity_key: Mapped[str | None] = mapped_column(String(120), index=True)
    period_label: Mapped[str | None] = mapped_column(String(40))     # "FY2024", "Q3-2025"
    # Sort key for the timeline. Label alone will not order correctly:
    # "FY2024" < "FY9999" is fine but "Q3-2025" vs "Q11-2025" is not.
    period_end: Mapped[date | None] = mapped_column(Date)

    # --- V3: stated uncertainty about the point inputs ---------------------
    # {metric: {low, mode, high}} for the axis inputs the matrix reads.
    uncertainty_inputs: Mapped[dict | None] = mapped_column(JsonBlob)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", order_by="Competitor.added_at"
    )
    swot_analyses: Mapped[list["SwotAnalysis"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="SwotAnalysis.generated_at",
    )
    attractiveness_results: Mapped[list["MarketAttractiveness"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="MarketAttractiveness.calculated_at",
    )
    pricing_recommendations: Mapped[list["PricingRecommendation"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="PricingRecommendation.calculated_at",
    )
    porters_analyses: Mapped[list["PortersAnalysis"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="PortersAnalysis.generated_at",
    )
    scenarios: Mapped[list["Scenario"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Scenario.created_at",
    )
    uncertainty_analyses: Mapped[list["UncertaintyAnalysis"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="UncertaintyAnalysis.generated_at",
    )
    reports: Mapped[list["StrategyReport"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="StrategyReport.generated_at",
    )
