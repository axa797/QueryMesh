"""Optional portal columns on users: email + password hash for signup/login.

Revision ID: 003_user_portal_login
Revises: 002_ingestion_jobs
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "003_user_portal_login"
down_revision = "002_ingestion_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT"))
    op.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"))
    op.execute(
        text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
        ON users (lower(email))
        WHERE email IS NOT NULL AND trim(email) <> ''
        """)
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_users_email_lower"))
    op.execute(
        text("""
        ALTER TABLE users
        DROP COLUMN IF EXISTS password_hash,
        DROP COLUMN IF EXISTS email
        """)
    )
