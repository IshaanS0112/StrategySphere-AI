"""V3.1: background jobs, and the indexes the read layer needs

Revision ID: 0004_v31_jobs_and_indexes
Revises: 0003_v3_uncertainty_and_portfolio
Create Date: 2026-09-28

Two things.

**The jobs table**, so long-running work (an EDGAR rebuild, a validation panel)
can be enqueued and polled instead of being refused with a 501 or blocking a
request for five minutes.

**The composite indexes the new query layer depends on.** Every stage reads
"the latest result for this company", which is now
``WHERE company_id = ? ORDER BY <timestamp> DESC LIMIT 1``. With only the
single-column ``company_id`` index that V1 created, the database finds the
right rows and then sorts them; with ``(company_id, timestamp DESC)`` it walks
the index backwards and stops at the first row. On the hot path that is the
difference between a sort of every run a company has ever had and reading one
index entry.

The plain ``company_id`` indexes are left in place. Dropping them for the
composite would be correct - a composite serves the prefix - but it is a
migration that can only be validated against production traffic, and the
storage saved is not worth the risk on a table this size.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_v31_jobs_and_indexes"
down_revision = "0003_v3_uncertainty_and_portfolio"
branch_labels = None
depends_on = None

JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")

# (table, timestamp column) for every per-company result table.
LATEST_INDEXES = [
    ("swot_analyses", "generated_at"),
    ("market_attractiveness", "calculated_at"),
    ("pricing_recommendations", "calculated_at"),
    ("strategy_reports", "generated_at"),
    ("porters_analyses", "generated_at"),
    ("uncertainty_analyses", "generated_at"),
]


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("result", JSONB),
        sa.Column("error", sa.String(2000)),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(500)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    # The reaper's query: RUNNING jobs ordered by how stale their heartbeat is.
    op.create_index("ix_jobs_state_heartbeat", "jobs", ["state", "heartbeat_at"])

    for table, timestamp in LATEST_INDEXES:
        op.create_index(
            f"ix_{table}_company_latest",
            table,
            ["company_id", sa.text(f"{timestamp} DESC")],
        )

    # Cursor pagination over companies orders by (created_at DESC, id DESC).
    op.create_index("ix_companies_created_id", "companies", ["created_at", "id"])
    # The timeline reads every period of an entity in period order.
    op.create_index("ix_companies_entity_period", "companies", ["entity_key", "period_end"])
    # The allocator resolves members to companies on every run.
    op.create_index("ix_allocation_runs_portfolio_created", "allocation_runs", ["portfolio_id", "generated_at"])


def downgrade() -> None:
    op.drop_index("ix_allocation_runs_portfolio_created", table_name="allocation_runs")
    op.drop_index("ix_companies_entity_period", table_name="companies")
    op.drop_index("ix_companies_created_id", table_name="companies")
    for table, _timestamp in LATEST_INDEXES:
        op.drop_index(f"ix_{table}_company_latest", table_name=table)
    op.drop_index("ix_jobs_state_heartbeat", table_name="jobs")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")
