"""Ingestion job persistence (Phase 2 spec_phase2).

Revision ID: 002_ingestion_jobs
Revises: 001_initial_schema
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "002_ingestion_jobs"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text("""
        CREATE TABLE ingestion_jobs (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            source TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'running', 'complete', 'failed')
            ),
            docs_indexed INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """)
    )
    op.execute(text("CREATE INDEX idx_ingestion_jobs_user_id ON ingestion_jobs(user_id)"))
    op.execute(text("CREATE INDEX idx_ingestion_jobs_status ON ingestion_jobs(status)"))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS ingestion_jobs"))
