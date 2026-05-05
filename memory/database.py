"""Database URL helpers and cheap connectivity checks for /health."""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger(__name__)


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


def _qdrant_debug_logging() -> bool:
    return os.environ.get("QDRANT_DEBUG", "").lower() in ("1", "true", "yes")


def _exception_detail(exc: BaseException) -> str:
    """Best-effort message; qdrant-client wraps httpx errors in ResponseHandlingException.source."""
    src = getattr(exc, "source", None)
    if src is not None and isinstance(src, BaseException):
        return f"{type(exc).__name__}: {_exception_detail(src)}"
    return f"{type(exc).__name__}: {exc!s}"


async def ping_qdrant(
    url: str,
    *,
    api_key: str | None = None,
    timeout: int = 60,
) -> bool:
    """Cheap round-trip for /health (same request shape as ``curl /collections``)."""
    base = (url or "").strip().rstrip("/")
    if not base:
        return False
    try:
        import httpx

        headers: dict[str, str] = {}
        if api_key:
            headers["api-key"] = api_key.strip()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base}/collections", headers=headers)
        if resp.status_code != 200:
            if _qdrant_debug_logging():
                log.warning(
                    "ping_qdrant failed: HTTP %s %s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
            return False
        return True
    except Exception as exc:
        msg = _exception_detail(exc)
        if _qdrant_debug_logging():
            log.warning("ping_qdrant failed: %s", msg)
        else:
            log.debug("ping_qdrant failed: %s", msg)
        return False
