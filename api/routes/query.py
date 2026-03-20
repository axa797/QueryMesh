"""POST /query (auth required; orchestration stub)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from memory.longterm import compact_to_token_budget, load_top_k_memories
from memory.redis_client import RedisDep
from memory.session import get_session_factory
from memory.session_envelope import resolve_session

from api.deps import CurrentUserId
from api.schemas.query import QueryRequest

router = APIRouter(tags=["query"])


def _stub_orchestrator_response(memory_compact: str) -> dict:
    """Placeholder until LangGraph; confirms memory is loaded before routing."""
    return {
        "status": "stub",
        "has_memory": bool(memory_compact.strip()),
    }


@router.post("/query")
async def post_query(
    user_id: CurrentUserId,
    body: QueryRequest,
    redis: RedisDep,
) -> dict:
    """Spec §8. session envelope (§7) then long-term memory (§7) before orchestrator."""
    t0 = time.monotonic()
    session_id, _thread_id = await resolve_session(redis, user_id, body.session_id)

    factory = get_session_factory()
    async with factory() as db:
        rows = await load_top_k_memories(db, user_id)
    memory_compact = compact_to_token_budget(rows)

    # Phase 7: LangGraph receives (body.query, _thread_id, memory_compact).
    latency_ms = max(0, int((time.monotonic() - t0) * 1000))
    return {
        "response": _stub_orchestrator_response(memory_compact),
        "trace_id": "stub",
        "latency_ms": latency_ms,
        "session_id": str(session_id),
    }
