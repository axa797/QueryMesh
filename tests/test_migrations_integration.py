"""Verify expected tables after `alembic upgrade head` (running Postgres required)."""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

EXPECTED_TABLES = frozenset(
    {
        "users",
        "api_keys",
        "user_memory",
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "alembic_version",
    }
)


def test_migration_tables_exist() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    async def _tables() -> set[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                res = await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
                )
                return {row[0] for row in res.fetchall()}
        finally:
            await engine.dispose()

    found = asyncio.run(_tables())
    assert EXPECTED_TABLES.issubset(found), f"missing: {EXPECTED_TABLES - found}"
