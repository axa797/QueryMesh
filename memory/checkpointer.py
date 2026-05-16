"""Psycopg connection pool for LangGraph `AsyncPostgresSaver` (spec §7).

`DATABASE_URL` uses SQLAlchemy's `postgresql+asyncpg://` scheme; Psycopg expects
`postgresql://`. Checkpoint DDL is applied by Alembic (`001_initial_schema`);
`AsyncPostgresSaver.setup()` is optional but safe after migrations.
"""

from __future__ import annotations

import asyncio
import uuid
from uuid import UUID

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


async def checkpoint_exists_for_thread(thread_id: str) -> bool:
    """Return True if LangGraph has persisted state for ``thread_id``."""
    pool = await get_checkpoint_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = %s LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()
            return row is not None


async def list_conversation_threads_for_user(user_internal_id: UUID) -> list[dict[str, str]]:
    """Distinct LangGraph threads for a user, recent activity first.

    Returns ``session_id`` (string) and ``last_checkpoint_id`` for ordering/display.
    """
    pattern = f"{user_internal_id}:%"
    pool = await get_checkpoint_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT thread_id, MAX(checkpoint_id) AS mx
                FROM checkpoints
                WHERE thread_id LIKE %s
                GROUP BY thread_id
                ORDER BY mx DESC
                """,
                (pattern,),
            )
            rows = await cur.fetchall()

    out: list[dict[str, str]] = []
    for row in rows:
        if not row:
            continue
        tid_s = str(row["thread_id"])
        mx = row["mx"]
        if ":" not in tid_s:
            continue
        _, sess = tid_s.split(":", 1)
        try:
            uuid.UUID(sess)
        except ValueError:
            continue
        out.append(
            {
                "session_id": sess,
                "last_checkpoint_id": str(mx) if mx is not None else "",
            }
        )
    return out


def reset_checkpoint_pool_for_tests() -> None:
    """Sync reset when tests cannot await pool close (leaks if pool was open)."""
    global _pool
    _pool = None
