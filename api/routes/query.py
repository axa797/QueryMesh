"""POST /query (auth required; orchestration stub)."""

from __future__ import annotations

import time

from fastapi import APIRouter
from graph.pipeline import get_compiled_query_graph
from memory.longterm import compact_to_token_budget, load_top_k_memories
from memory.redis_client import RedisDep
from memory.session import get_session_factory
from memory.session_envelope import resolve_session
from observability.instrumentation import build_langgraph_invoke_config, flush_langfuse

from api.deps import CurrentUserId
from api.schemas.query import QueryRequest

router = APIRouter(tags=["query"])


@router.post("/query")
async def post_query(
    user_id: CurrentUserId,
    body: QueryRequest,
    redis: RedisDep,
) -> dict:
    """Spec §8. Session → long-term memory → LangGraph (§7) before full multi-agent."""
    t0 = time.monotonic()
    session_id, thread_id = await resolve_session(redis, user_id, body.session_id)

    factory = get_session_factory()
    async with factory() as db:
        rows = await load_top_k_memories(db, user_id)
    memory_compact = compact_to_token_budget(rows)

    graph = await get_compiled_query_graph()
    invoke_cfg, trace_id = build_langgraph_invoke_config(
        thread_id=thread_id,
        session_id=str(session_id),
    )
    try:
        graph_out = await graph.ainvoke(
            {
                "user_id": str(user_id),
                "query": body.query,
                "memory_compact": memory_compact,
            },
            config=invoke_cfg,
        )
    finally:
        flush_langfuse()

    latency_ms = max(0, int((time.monotonic() - t0) * 1000))
    return {
        "response": {
            "status": "ok",
            "has_memory": bool(memory_compact.strip()),
            "echo_reply": graph_out.get("echo_reply"),
            "orchestrator": graph_out.get("orchestrator"),
            "retrieval_hits": graph_out.get("retrieval_hits") or [],
            "analytics_structured": graph_out.get("analytics_structured"),
            "code_structured": graph_out.get("code_structured"),
            "rag_structured": graph_out.get("rag_structured"),
            "synthesis": graph_out.get("synthesis"),
        },
        "trace_id": trace_id,
        "latency_ms": latency_ms,
        "session_id": str(session_id),
    }
