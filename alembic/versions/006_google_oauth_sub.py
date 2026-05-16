"""OAuth Google subject on portal users.

Revision ID: 006_google_oauth_sub
Revises: 005_eval_reports_table
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "006_google_oauth_sub"
down_revision = "005_eval_reports_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub TEXT"))
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub
            ON users (google_sub)
            WHERE google_sub IS NOT NULL
            """
        ),
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_users_google_sub"))
    op.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS google_sub"))
