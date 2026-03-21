"""Psycopg connection pool for LangGraph `AsyncPostgresSaver` (spec §7).

`DATABASE_URL` uses SQLAlchemy's `postgresql+asyncpg://` scheme; Psycopg expects
`postgresql://`. Checkpoint DDL is applied by Alembic (`001_initial_schema`);
`AsyncPostgresSaver.setup()` is optional but safe after migrations.
"""

from __future__ import annotations

import asyncio

from api.settings import get_settings
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None
_pool_lock = asyncio.Lock()


def database_url_to_psycopg(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


async def get_checkpoint_pool() -> AsyncConnectionPool:
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = AsyncConnectionPool(
                conninfo=database_url_to_psycopg(get_settings().database_url),
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                min_size=1,
                max_size=10,
                open=False,
            )
            await _pool.open()
        return _pool


async def dispose_checkpoint_pool() -> None:
    global _pool
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None


def reset_checkpoint_pool_for_tests() -> None:
    """Sync reset when tests cannot await pool close (leaks if pool was open)."""
    global _pool
    _pool = None
