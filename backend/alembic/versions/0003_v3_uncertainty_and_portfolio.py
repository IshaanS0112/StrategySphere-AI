"""V3: uncertainty propagation and portfolio capital allocation"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_v3_uncertainty_and_portfolio"
down_revision = "0002_v2_periods_porters_scenarios"
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # --- Pillar B: the distributions live beside the point inputs ----------
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("uncertainty_inputs", JSONB))

    op.create_table(
        "uncertainty_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL rather than CASCADE: the run is still a true record of what
        # was computed even if the matrix row it described is later deleted.
        sa.Column(
            "market_attractiveness_id",
            sa.Uuid(),
            sa.ForeignKey("market_attractiveness.id", ondelete="SET NULL"),
        ),
        sa.Column("point_quadrant", sa.String(30), nullable=False),
        sa.Column("modal_quadrant", sa.String(30), nullable=False),
        sa.Column("quadrant_probabilities", JSONB, nullable=False),
        sa.Column("attractiveness_ci_90", JSONB, nullable=False),
        sa.Column("strength_ci_90", JSONB, nullable=False),
        sa.Column("entropy_bits", sa.Float(), nullable=False),
        sa.Column("verdict_stability", sa.String(20), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_uncertainty_analyses_company_id", "uncertainty_analyses", ["company_id"]
    )

    # --- Pillar C: portfolios ---------------------------------------------
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Uuid(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Bubble size on the grid, and the base of the harvest contribution.
        sa.Column("revenue", sa.Float()),
        sa.Column("capital_requested", sa.Float(), nullable=False),
        sa.Column("capital_floor", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_portfolio_members_portfolio_id", "portfolio_members", ["portfolio_id"]
    )
    op.create_index("ix_portfolio_members_company_id", "portfolio_members", ["company_id"])

    op.create_table(
        "allocation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Uuid(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Stored rather than read back off the portfolio: a run is a record of the
        # budget it was actually computed against, and the portfolio's budget can
        # change afterwards.
        sa.Column("budget", sa.Float(), nullable=False),
        sa.Column("allocations", JSONB, nullable=False),
        sa.Column("unfunded", JSONB, nullable=False),
        sa.Column("marginal_unit", JSONB),
        sa.Column("harvest_contribution", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_allocation_runs_portfolio_id", "allocation_runs", ["portfolio_id"])


def downgrade() -> None:
    op.drop_table("allocation_runs")
    op.drop_table("portfolio_members")
    op.drop_table("portfolios")
    op.drop_index("ix_uncertainty_analyses_company_id", table_name="uncertainty_analyses")
    op.drop_table("uncertainty_analyses")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("uncertainty_inputs")
