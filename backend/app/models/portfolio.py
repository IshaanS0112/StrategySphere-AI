"""V3: portfolios, their members, and the allocation runs over them."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))

    # The default budget for this portfolio.
    budget: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    members: Mapped[list["PortfolioMember"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    allocation_runs: Mapped[list["AllocationRun"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="AllocationRun.generated_at",
    )


class PortfolioMember(Base):
    __tablename__ = "portfolio_members"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Bubble area on the grid, and the base the harvest contribution is taken from.
    revenue: Mapped[float | None] = mapped_column(Float)

    capital_requested: Mapped[float] = mapped_column(Float, nullable=False)
    # The minimum to keep the unit operating. Funded before anything
    # discretionary, and never silently trimmed.
    capital_floor: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="members")
    company: Mapped["Company"] = relationship()


class AllocationRun(Base):
    """One budget-constrained allocation over one portfolio."""

    __tablename__ = "allocation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    budget: Mapped[float] = mapped_column(Float, nullable=False)

    # Per member: requested, floor, allocated, priority, outcome and the reason.
    allocations: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    unfunded: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    # The highest-priority unit that did not get its full request.
    marginal_unit: Mapped[dict | None] = mapped_column(JsonBlob)

    harvest_contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="allocation_runs")
