"""V1 baseline schema"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_v1_baseline"
down_revision = None
branch_labels = None
depends_on = None

# JSON on SQLite, JSONB on Postgres - the same variant the models declare.
JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("industry", sa.String(100)),
        sa.Column("financial_data", JSONB, nullable=False),
        sa.Column("market_data", JSONB, nullable=False),
        sa.Column("feature_scores", JSONB, nullable=False),
        sa.Column("qualitative_inputs", JSONB, nullable=False),
        sa.Column("data_source", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "competitors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("competitor_name", sa.String(200), nullable=False),
        sa.Column("price_point", sa.Float()),
        sa.Column("market_share_pct", sa.Float()),
        sa.Column("feature_scores", JSONB, nullable=False),
        sa.Column("financial_data", JSONB, nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_competitors_company_id", "competitors", ["company_id"])

    op.create_table(
        "swot_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strengths", JSONB, nullable=False),
        sa.Column("weaknesses", JSONB, nullable=False),
        sa.Column("opportunities", JSONB, nullable=False),
        sa.Column("threats", JSONB, nullable=False),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_swot_analyses_company_id", "swot_analyses", ["company_id"])

    op.create_table(
        "market_attractiveness",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "swot_analysis_id",
            sa.Uuid(),
            sa.ForeignKey("swot_analyses.id", ondelete="SET NULL"),
        ),
        sa.Column("market_growth_score", sa.Float(), nullable=False),
        sa.Column("market_size_score", sa.Float(), nullable=False),
        sa.Column("profitability_score", sa.Float(), nullable=False),
        sa.Column("competitive_intensity_score", sa.Float(), nullable=False),
        sa.Column("overall_attractiveness_score", sa.Float(), nullable=False),
        sa.Column("competitive_strength_score", sa.Float(), nullable=False),
        sa.Column("quadrant", sa.String(30), nullable=False),
        sa.Column("borderline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_market_attractiveness_company_id", "market_attractiveness", ["company_id"]
    )

    op.create_table(
        "pricing_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cost_base", sa.Float(), nullable=False),
        sa.Column("competitor_avg_price", sa.Float()),
        sa.Column("target_margin_pct", sa.Float(), nullable=False),
        sa.Column("margin_basis", sa.String(10), nullable=False),
        sa.Column("recommended_price_range", JSONB, nullable=False),
        sa.Column("reasoning", JSONB, nullable=False),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_pricing_recommendations_company_id", "pricing_recommendations", ["company_id"]
    )

    op.create_table(
        "strategy_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("structured_context", JSONB, nullable=False),
        sa.Column("ai_narrative", JSONB),
        sa.Column("narrative_source", sa.String(20)),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_strategy_reports_company_id", "strategy_reports", ["company_id"])


def downgrade() -> None:
    op.drop_table("strategy_reports")
    op.drop_table("pricing_recommendations")
    op.drop_table("market_attractiveness")
    op.drop_table("swot_analyses")
    op.drop_table("competitors")
    op.drop_table("companies")
