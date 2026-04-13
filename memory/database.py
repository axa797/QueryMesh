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


async def ping_redis(url: str) -> bool:
    import redis.asyncio as redis

    client = redis.from_url(url, decode_responses=True)
    try:
        pong = await client.ping()
        return pong is True
    except Exception:
        return False
    finally:
        await client.aclose()


async def ping_qdrant(url: str, *, api_key: str | None = None) -> bool:
    """Cheap TCP-round-trip check (collections list) for /health."""
    try:
        from qdrant_client import AsyncQdrantClient

        kwargs: dict = {"url": url, "check_compatibility": False}
        if api_key:
            kwargs["api_key"] = api_key
        client = AsyncQdrantClient(**kwargs)
        try:
            await client.get_collections()
            return True
        finally:
            await client.close()
    except Exception:
        return False
