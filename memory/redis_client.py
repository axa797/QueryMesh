"""Async Redis client for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import redis.asyncio as redis
from api.settings import get_settings
from fastapi import Depends

_client: redis.Redis | None = None


async def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
        )
    return _client


async def redis_dependency() -> AsyncIterator[redis.Redis]:
    yield await get_redis_client()


RedisDep = Annotated[redis.Redis, Depends(redis_dependency)]


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
