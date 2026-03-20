"""Long-term memory ordering against Postgres."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from memory.longterm import load_top_k_memories
from memory.session import session_scope
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_sql_type_priority_and_last_accessed() -> None:
    u = uuid.uuid4()

    async def _run() -> None:
        async with session_scope() as s:
            await s.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": u})
            await s.execute(
                text(
                    """
                    INSERT INTO user_memory (user_id, memory_type, content, last_accessed)
                    VALUES (:u, 'history', 'h-old', '2020-01-01T00:00:00Z')
                    """
                ),
                {"u": u},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO user_memory (user_id, memory_type, content, last_accessed)
                    VALUES (:u, 'history', 'h-new', '2025-01-01T00:00:00Z')
                    """
                ),
                {"u": u},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO user_memory (user_id, memory_type, content, last_accessed)
                    VALUES (:u, 'preference', 'pref', '2019-01-01T00:00:00Z')
                    """
                ),
                {"u": u},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO user_memory (user_id, memory_type, content, last_accessed)
                    VALUES (:u, 'context', 'ctx', '2024-01-01T00:00:00Z')
                    """
                ),
                {"u": u},
            )

        try:
            async with session_scope() as s:
                rows = await load_top_k_memories(s, u, k=5)
            types = [r.memory_type for r in rows]
            assert types[:3] == ["preference", "context", "history"]
            hist = [r for r in rows if r.memory_type == "history"]
            assert [r.content for r in hist] == ["h-new", "h-old"]
        finally:
            async with session_scope() as s:
                await s.execute(text("DELETE FROM user_memory WHERE user_id = :u"), {"u": u})
                await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})

    asyncio.run(_run())
