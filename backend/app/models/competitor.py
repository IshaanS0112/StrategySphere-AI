"""Competitors: the peer set a company is benchmarked against."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base, JsonBlob, utc_now

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.company import Company


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_name: Mapped[str] = mapped_column(String(200), nullable=False)

    price_point: Mapped[float | None] = mapped_column(Float)
    market_share_pct: Mapped[float | None] = mapped_column(Float)

    # {feature_name: score} on a shared 1-5 scale.
    feature_scores: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    # Same shape as Company.financial_data. Supplying it lets the SWOT engine
    # benchmark against the peer median instead of a static industry table.
    financial_data: Mapped[dict] = mapped_column(JsonBlob, nullable=False, default=dict)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="competitors")
