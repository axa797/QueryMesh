"""App identity memory tables + LangGraph checkpoint schema.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-30

Spec §7 (`users`, `api_keys`, `user_memory`) plus tables from
`langgraph.checkpoint.postgres.base.MIGRATIONS` v0–v10. Indexes that upstream
runs as CONCURRENTLY are created as normal indexes here so they run inside
Alembic's transaction. `checkpoint_migrations` is seeded so
`AsyncPostgresSaver.setup()` is a no-op.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text("""
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)
    )
    op.execute(
        text("""
        CREATE TABLE api_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            key_digest TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW(),
            revoked_at TIMESTAMP
        )
        """)
    )
    op.execute(
        text("""
        CREATE INDEX idx_api_keys_active ON api_keys(key_digest)
        WHERE revoked_at IS NULL
        """)
    )
    op.execute(
        text("""
        CREATE TABLE user_memory (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            memory_type TEXT NOT NULL CHECK (memory_type IN ('preference', 'context', 'history')),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            last_accessed TIMESTAMP
        )
        """)
    )
    op.execute(
        text("CREATE INDEX idx_user_memory_user_id ON user_memory(user_id)"),
    )

    op.execute(
        text("""
        CREATE TABLE checkpoint_migrations (
            v INTEGER PRIMARY KEY
        )
        """)
    )
    op.execute(
        text("""
        CREATE TABLE checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """)
    )
    op.execute(
        text("""
        CREATE TABLE checkpoint_blobs (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL,
            version TEXT NOT NULL,
            type TEXT NOT NULL,
            blob BYTEA,
            PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
        )
        """)
    )
    op.execute(
        text("""
        CREATE TABLE checkpoint_writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            blob BYTEA NOT NULL,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        )
        """)
    )
    op.execute(text("ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP NOT NULL"))
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)",
        ),
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON "
            "checkpoint_blobs(thread_id)",
        ),
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON "
            "checkpoint_writes(thread_id)",
        ),
    )
    op.execute(
        text(
            "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path "
            "TEXT NOT NULL DEFAULT ''",
        ),
    )
    op.execute(
        text("""
        INSERT INTO checkpoint_migrations (v) VALUES
        (0), (1), (2), (3), (4), (5), (6), (7), (8), (9), (10)
        ON CONFLICT DO NOTHING
        """)
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS checkpoint_writes CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS checkpoint_blobs CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS checkpoints CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS checkpoint_migrations CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS user_memory CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS api_keys CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS users CASCADE"))
