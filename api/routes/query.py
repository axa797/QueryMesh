"""POST /query (auth required; orchestration stub)."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import CurrentUserId

router = APIRouter(tags=["query"])


@router.post("/query")
async def post_query(_user_id: CurrentUserId) -> dict:
    """Spec §8. Agent pipeline not wired yet — proves auth + stable response shape."""
    return {
        "response": {"status": "stub"},
        "trace_id": "stub",
        "latency_ms": 0,
        "session_id": "stub",
    }
