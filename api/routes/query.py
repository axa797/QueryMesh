"""POST /query (auth required; orchestration stub)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from memory.redis_client import RedisDep
from memory.session_envelope import resolve_session

from api.deps import CurrentUserId
from api.schemas.query import QueryRequest

router = APIRouter(tags=["query"])


@router.post("/query")
async def post_query(
    user_id: CurrentUserId,
    body: QueryRequest,
    redis: RedisDep,
) -> dict:
    """Spec §8. session_id optional; envelope in Redis (§7)."""
    t0 = time.monotonic()
    session_id, _thread_id = await resolve_session(redis, user_id, body.session_id)
    latency_ms = max(0, int((time.monotonic() - t0) * 1000))
    return {
        "response": {"status": "stub"},
        "trace_id": "stub",
        "latency_ms": latency_ms,
        "session_id": str(session_id),
    }
