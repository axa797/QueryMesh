"""Persisted RAGAS aggregate + per-row metrics (optional Langfuse trace id).

Revision ID: 005_eval_reports_table
Revises: 004_ingest_service_user
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "005_eval_reports_table"
down_revision = "004_ingest_service_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text("""
        CREATE TABLE eval_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            mode TEXT NOT NULL,
            n_samples INTEGER NOT NULL,
            aggregate_metrics JSONB NOT NULL,
            per_row_metrics JSONB,
            judge_model TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            langfuse_trace_id TEXT,
            trigger_source TEXT NOT NULL DEFAULT 'manual',
            git_commit TEXT
        )
        """),
    )
    op.execute(
        text("CREATE INDEX idx_eval_reports_created_at ON eval_reports (created_at DESC)"),
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS eval_reports"))
