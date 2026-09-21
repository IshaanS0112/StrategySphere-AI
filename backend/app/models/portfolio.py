"""V3: portfolios, their members, and the allocation runs over them.

A portfolio is a named set of business units competing for one budget. A member
points at an existing ``companies`` row — which, since V2, is a company *as
reported for one period* — rather than duplicating its identity or its scores.
That is what keeps a unit's position on the portfolio grid identical to the one
its own page shows: there is only one scored row, and both views read it.
"""

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

    # The default budget for this portfolio. Each allocation run stores the
    # budget it was actually computed against, so changing this never rewrites
    # the history of what was decided.
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

    # Bubble area on the grid, and the base the harvest contribution is taken
    # from. Nullable: a unit can be scored without disclosing a revenue figure,
    # and a HARVEST_DIVEST unit with no revenue simply contributes nothing and
    # says so rather than contributing a guess.
    revenue: Mapped[float | None] = mapped_column(Float)

    capital_requested: Mapped[float] = mapped_column(Float, nullable=False)
    # The minimum to keep the unit operating. Funded before anything
    # discretionary, and never silently trimmed.
    capital_floor: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="members")
    company: Mapped["Company"] = relationship()


class AllocationRun(Base):
    """One budget-constrained allocation over one portfolio.

    ``calculation_basis`` carries the priority formula, the allocation order and
    the PROJECT-DEFINED label, so a stored run can be re-derived by hand from
    the row that contains it — the same contract every other result table here
    honours.
    """

    __tablename__ = "allocation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    budget: Mapped[float] = mapped_column(Float, nullable=False)

    # Per member: requested, floor, allocated, priority, outcome and the reason.
    allocations: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    unfunded: Mapped[list] = mapped_column(JsonBlob, nullable=False, default=list)
    # The highest-priority unit that did not get its full request. Null when
    # everything was funded, which is a different statement from "nobody missed
    # out narrowly".
    marginal_unit: Mapped[dict | None] = mapped_column(JsonBlob)

    harvest_contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    calculation_basis: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="allocation_runs")
