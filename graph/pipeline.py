"""LangGraph query pipeline through orchestration + RAG + optional analytics (Phase 7–11)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from agents.analytics_agent import run_analytics
from agents.orchestrator import run_orchestrator
from agents.rag_agent import run_rag_structured
from agents.synthesizer import run_synthesizer
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from memory.checkpointer import get_checkpoint_pool
from tools.retrieval_tool import retrieve_context
from typing_extensions import TypedDict

_compiled_lock = asyncio.Lock()
_compiled_graph: Any = None


class QueryGraphState(TypedDict, total=False):
    """Graph state: user query + long-term memory block + node outputs."""

    user_id: str
    query: str
    memory_compact: str
    echo_reply: str
    orchestrator: dict[str, Any]
    retrieval_hits: list[dict[str, Any]]
    analytics_structured: dict[str, Any]
    rag_structured: dict[str, Any]
    synthesis: dict[str, Any]


def _intents(state: QueryGraphState) -> list[str]:
    orch = state.get("orchestrator") or {}
    raw = orch.get("intents") if isinstance(orch, dict) else None
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def echo_node(state: QueryGraphState) -> dict[str, str]:
    q = (state.get("query") or "").strip()
    return {"echo_reply": f"echo:{q[:2000]}"}


async def orchestrator_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    plan = await run_orchestrator(
        state.get("query") or "",
        state.get("memory_compact") or "",
    )
    return {"orchestrator": plan}


async def retrieve_node(state: QueryGraphState) -> dict[str, list[dict[str, Any]]]:
    if "retrieval" not in _intents(state):
        return {"retrieval_hits": []}
    stub = state.get("orchestrator") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("retrieval") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    hits = await retrieve_context(q, top_k=5)
    return {"retrieval_hits": hits}


async def analytics_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    if "analytics" not in _intents(state):
        return {
            "analytics_structured": {
                "source": "skipped",
                "interpretation": "Analytics intent not selected for this query.",
            },
        }
    stub = state.get("orchestrator") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("analytics") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    out = await run_analytics(q)
    return {"analytics_structured": out}


async def rag_structured_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    if "retrieval" not in _intents(state):
        return {
            "rag_structured": {
                "answer": "Retrieval was not routed for this query.",
                "citations": [],
                "confidence": "low",
                "source": "skipped",
            },
        }
    rag = await run_rag_structured(
        state.get("query") or "",
        state.get("retrieval_hits") or [],
    )
    return {"rag_structured": rag}


async def synthesizer_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    uid_s = (state.get("user_id") or "").strip()
    if not uid_s:
        raise ValueError("query graph state requires user_id")
    syn = await run_synthesizer(
        state.get("query") or "",
        state.get("memory_compact") or "",
        state.get("orchestrator") or {},
        state.get("rag_structured") or {},
        state.get("analytics_structured"),
        UUID(uid_s),
    )
    return {"synthesis": syn}


def build_query_graph() -> StateGraph:
    g: StateGraph = StateGraph(QueryGraphState)
    g.add_node("echo", echo_node)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("analytics", analytics_node)
    g.add_node("rag_structured", rag_structured_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_edge(START, "echo")
    g.add_edge("echo", "orchestrator")
    g.add_edge("orchestrator", "retrieve")
    g.add_edge("retrieve", "analytics")
    g.add_edge("analytics", "rag_structured")
    g.add_edge("rag_structured", "synthesizer")
    g.add_edge("synthesizer", END)
    return g


async def get_compiled_query_graph() -> Any:
    """Compiled graph with Postgres checkpointer; one per process (async init)."""
    global _compiled_graph
    async with _compiled_lock:
        if _compiled_graph is None:
            pool = await get_checkpoint_pool()
            saver = AsyncPostgresSaver(pool)
            _compiled_graph = build_query_graph().compile(checkpointer=saver)
        return _compiled_graph


async def dispose_compiled_query_graph() -> None:
    global _compiled_graph
    async with _compiled_lock:
        _compiled_graph = None


def reset_compiled_graph_for_tests() -> None:
    global _compiled_graph
    _compiled_graph = None
