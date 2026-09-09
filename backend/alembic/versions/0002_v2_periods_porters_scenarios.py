"""V2: period dimension, Porter's Five Forces, and scenarios

Revision ID: 0002_v2_periods_porters_scenarios
Revises: 0001_v1_baseline
Create Date: 2026-09-08

Additive throughout. The three new columns on ``companies`` are nullable, so
every V1 row remains valid and simply has no timeline — a company with no
``entity_key`` behaves exactly as it did in V1. Nothing is backfilled, because
inventing a period label for a row that never had one would be fabricating
data, and a NULL that reads as "this was a standalone snapshot" is true.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_v2_periods_porters_scenarios"
down_revision = "0001_v1_baseline"
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # --- period dimension on companies -------------------------------------
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("entity_key", sa.String(120)))
        batch.add_column(sa.Column("period_label", sa.String(40)))
        batch.add_column(sa.Column("period_end", sa.Date()))
    op.create_index("ix_companies_entity_key", "companies", ["entity_key"])

    # --- Porter's Five Forces ----------------------------------------------
    op.create_table(
        "porters_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("forces", JSONB, nullable=False),
        # Nullable: an industry where fewer than two forces could be scored has
        # no meaningful composite, and 0.0 would read as "no competitive
        # pressure" rather than "not enough data".
        sa.Column("composite_score", sa.Float()),
        sa.Column("industry_attractiveness", sa.String(20)),
        sa.Column("forces_scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calculation_basis", JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_porters_analyses_company_id", "porters_analyses", ["company_id"])

    # --- what-if scenarios --------------------------------------------------
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("overrides", JSONB, nullable=False),
        sa.Column("baseline_snapshot", JSONB, nullable=False),
        sa.Column("scenario_result", JSONB, nullable=False),
        sa.Column("delta", JSONB, nullable=False),
        sa.Column("quadrant_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scenarios_company_id", "scenarios", ["company_id"])


def downgrade() -> None:
    op.drop_table("scenarios")
    op.drop_table("porters_analyses")
    op.drop_index("ix_companies_entity_key", table_name="companies")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("period_end")
        batch.drop_column("period_label")
        batch.drop_column("entity_key")
