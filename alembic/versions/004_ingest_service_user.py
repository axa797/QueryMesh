"""Seed system user row for INGEST_TOKEN-backed POST /ingest jobs.

`api.deps._INGEST_SERVICE_UUID` must exist in `users` so `ingestion_jobs.user_id`
FK inserts succeed.

Revision ID: 004_ingest_service_user
Revises: 003_user_portal_login
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "004_ingest_service_user"
down_revision = "003_user_portal_login"
branch_labels = None
depends_on = None

# Must match api.deps._INGEST_SERVICE_UUID
_INGEST_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        text(
            f"INSERT INTO users (id) VALUES ('{_INGEST_USER_ID}'::uuid) "
            "ON CONFLICT (id) DO NOTHING",
        ),
    )


def downgrade() -> None:
    op.execute(
        text(f"DELETE FROM ingestion_jobs WHERE user_id = '{_INGEST_USER_ID}'::uuid"),
    )
    op.execute(text(f"DELETE FROM users WHERE id = '{_INGEST_USER_ID}'::uuid"))
