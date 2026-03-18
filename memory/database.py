"""Database URL helpers and cheap connectivity checks for /health."""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


async def ping_postgres(url: str) -> bool:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()
