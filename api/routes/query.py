"""POST /query and POST /query/stream (Bearer auth required)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from graph.pipeline import get_compiled_query_graph
from langchain_core.messages import HumanMessage
from memory.longterm import compact_to_token_budget, load_top_k_memories
from memory.redis_client import RedisDep
from memory.session import get_session_factory
from memory.session_envelope import resolve_session
from observability.gcp_monitoring import record_http_request
from observability.instrumentation import build_langgraph_invoke_config, flush_langfuse
from observability.query_intent import intent_bucket_from_graph_out
from observability.query_request_log import log_query_request

from api.deps import CurrentUserId
from api.schemas.query import QueryRequest

router = APIRouter(tags=["query"])

_PIPELINE_LOG_KEYS: frozenset[str] = frozenset(
    {
        "orchestrator_ms",
        "retrieve_embed_ms",
        "retrieve_qdrant_ms",
        "retrieve_vertex_rerank_ms",
        "dense_prefetch_count",
        "retrieval_returned_count",
        "retrieve_total_ms",
        "hybrid_lexical_rrf",
        "rerank_skip_reason",
        "rerank_order_changed",
        "retrieval_skipped",
        "rag_structured_skipped",
        "specialists_ms",
        "rag_structured_ms",
        "synthesizer_ms",
    }
)


def _pipeline_log_extra(graph_out: dict[str, Any]) -> dict[str, Any]:
    pm = graph_out.get("pipeline_metrics")
    if not isinstance(pm, dict):
        return {}
    out: dict[str, Any] = {}
    for k in _PIPELINE_LOG_KEYS:
        if k in pm:
            out[k] = pm[k]
    return out


def _compact_sources(retrieval_hits: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in retrieval_hits:
        if not isinstance(h, dict):
            continue
        txt = str(h.get("text") or "")
        out.append(
            {
                "point_id": str(h.get("point_id") or ""),
                "source_doc": str(h.get("source_doc") or ""),
                "section": str(h.get("section") or ""),
                "product": str(h.get("product") or ""),
                "page_number": h.get("page_number"),
                "score": h.get("score"),
                "excerpt": txt[:400],
            }
        )
    return out


def _build_success_payload(
    *,
    graph_out: dict[str, Any],
    trace_id: str,
    session_id_str: str,
    memory_compact: str,
    latency_ms: int,
) -> dict[str, Any]:
    hits_raw = graph_out.get("retrieval_hits") or []
    retrieval_hits: list[Any] = hits_raw if isinstance(hits_raw, list) else []

    return {
        "response": {
            "status": "ok",
            "has_memory": bool(memory_compact.strip()),
            "echo_reply": graph_out.get("echo_reply"),
            "orchestrator": graph_out.get("orchestrator"),
            "retrieval_hits": retrieval_hits,
            "source_cards": _compact_sources(retrieval_hits),
            "analytics_structured": graph_out.get("analytics_structured"),
            "code_structured": graph_out.get("code_structured"),
            "rag_structured": graph_out.get("rag_structured"),
            "synthesis": graph_out.get("synthesis"),
        },
        "trace_id": trace_id,
        "latency_ms": latency_ms,
        "session_id": session_id_str,
    }


def _sse_chunk(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@dataclass(frozen=True)
class _TurnContext:
    session_id_str: str
    invoke_cfg: dict[str, Any]
    trace_id: str
    memory_compact: str
    invoke_input: dict[str, Any]


async def _load_turn(user_id: UUID, body: QueryRequest, redis: RedisDep) -> _TurnContext:
    session_id, thread_id = await resolve_session(redis, user_id, body.session_id)
    session_id_str = str(session_id)

    factory = get_session_factory()
    async with factory() as db:
        rows = await load_top_k_memories(db, user_id)
    memory_compact = compact_to_token_budget(rows)

    invoke_cfg, trace_id = build_langgraph_invoke_config(
        thread_id=thread_id,
        session_id=session_id_str,
        user_id=str(user_id),
    )
    invoke_input: dict[str, Any] = {
        "user_id": str(user_id),
        "query": body.query,
        "memory_compact": memory_compact,
        "messages": [HumanMessage(content=body.query.strip())],
    }
    return _TurnContext(
        session_id_str=session_id_str,
        invoke_cfg=invoke_cfg,
        trace_id=trace_id,
        memory_compact=memory_compact,
        invoke_input=invoke_input,
    )


@router.post("/query")
async def post_query(
    user_id: CurrentUserId,
    body: QueryRequest,
    redis: RedisDep,
) -> dict[str, Any]:
    """Session → long-term memory → LangGraph checkpointed graph."""
    t0 = time.monotonic()
    http_status = 500
    intent_bucket = "unknown"
    graph_out: dict[str, Any] = {}
    trace_id = ""
    session_id_str = ""
    memory_compact = ""

    try:
        turn = await _load_turn(user_id, body, redis)
        session_id_str = turn.session_id_str
        trace_id = turn.trace_id
        memory_compact = turn.memory_compact

        graph = await get_compiled_query_graph()
        graph_out = await graph.ainvoke(turn.invoke_input, config=turn.invoke_cfg)

        intent_bucket = intent_bucket_from_graph_out(graph_out)
        http_status = 200
    except Exception:
        latency_ms = max(0, int((time.monotonic() - t0) * 1000))
        log_query_request(
            route="/query",
            method="POST",
            http_status=500,
            latency_ms=latency_ms,
            intent_bucket="error",
        )
        raise
    finally:
        flush_langfuse()

    latency_ms = max(0, int((time.monotonic() - t0) * 1000))
    extra = _pipeline_log_extra(graph_out)
    retrieval_hits = graph_out.get("retrieval_hits") or []
    if isinstance(retrieval_hits, list):
        extra["retrieval_hit_count_final"] = len(retrieval_hits)

    log_query_request(
        route="/query",
        method="POST",
        http_status=http_status,
        latency_ms=latency_ms,
        intent_bucket=intent_bucket,
        extra=extra,
    )
    record_http_request(
        route="/query",
        method="POST",
        status_code=http_status,
        latency_ms=latency_ms,
    )
    return _build_success_payload(
        graph_out=graph_out,
        trace_id=trace_id,
        session_id_str=session_id_str,
        memory_compact=memory_compact,
        latency_ms=latency_ms,
    )


@router.post("/query/stream")
async def post_query_stream(
    user_id: CurrentUserId,
    body: QueryRequest,
    redis: RedisDep,
) -> StreamingResponse:
    """Stream LangGraph with coarse ``phase`` events, then a JSON ``done`` payload."""

    async def event_iter() -> AsyncIterator[str]:
        t0 = time.monotonic()
        trace_id = ""
        session_id_str = ""
        memory_compact = ""
        graph_out: dict[str, Any] = {}
        try:
            turn = await _load_turn(user_id, body, redis)
            session_id_str = turn.session_id_str
            trace_id = turn.trace_id
            memory_compact = turn.memory_compact

            graph = await get_compiled_query_graph()

            async for update in graph.astream(
                turn.invoke_input,
                config=turn.invoke_cfg,
                stream_mode="updates",
            ):
                for node_name in update:
                    yield _sse_chunk({"type": "phase", "node": node_name})

            snap = await graph.aget_state(turn.invoke_cfg)
            vals = getattr(snap, "values", None)
            graph_out = dict(vals) if isinstance(vals, dict) else {}

            intent_bucket = intent_bucket_from_graph_out(graph_out)
            http_status = 200
            latency_ms = max(0, int((time.monotonic() - t0) * 1000))

            extra = _pipeline_log_extra(graph_out)
            rh = graph_out.get("retrieval_hits") or []
            if isinstance(rh, list):
                extra["retrieval_hit_count_final"] = len(rh)

            log_query_request(
                route="/query/stream",
                method="POST",
                http_status=http_status,
                latency_ms=latency_ms,
                intent_bucket=intent_bucket,
                extra=extra,
            )
            record_http_request(
                route="/query/stream",
                method="POST",
                status_code=http_status,
                latency_ms=latency_ms,
            )

            payload = _build_success_payload(
                graph_out=graph_out,
                trace_id=trace_id,
                session_id_str=session_id_str,
                memory_compact=memory_compact,
                latency_ms=latency_ms,
            )
            yield _sse_chunk({"type": "done", "payload": payload})
        except Exception as exc:
            latency_ms = max(0, int((time.monotonic() - t0) * 1000))
            log_query_request(
                route="/query/stream",
                method="POST",
                http_status=500,
                latency_ms=latency_ms,
                intent_bucket="error",
            )
            record_http_request(
                route="/query/stream",
                method="POST",
                status_code=500,
                latency_ms=latency_ms,
            )
            yield _sse_chunk({"type": "error", "message": str(exc) or "stream_failed"})
        finally:
            flush_langfuse()

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
