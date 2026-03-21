"""LangGraph query pipeline: echo → orchestrator stub → retrieve (Phase 7–8)."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from memory.checkpointer import get_checkpoint_pool
from tools.retrieval_tool import retrieve_context
from typing_extensions import TypedDict

_compiled_lock = asyncio.Lock()
_compiled_graph: Any = None


class QueryGraphState(TypedDict, total=False):
    """Graph state: user query + long-term memory block + node outputs."""

    query: str
    memory_compact: str
    echo_reply: str
    orchestrator_stub: dict[str, Any]
    retrieval_hits: list[dict[str, Any]]


def echo_node(state: QueryGraphState) -> dict[str, str]:
    q = (state.get("query") or "").strip()
    return {"echo_reply": f"echo:{q[:2000]}"}


def orchestrator_stub_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    """Placeholder routing object until real orchestrator (spec §6.1)."""
    return {
        "orchestrator_stub": {
            "intents": ["retrieval"],
            "parallel": False,
            "rewritten_queries": {"retrieval": (state.get("query") or "").strip()},
            "stub": True,
        },
    }


async def retrieve_node(state: QueryGraphState) -> dict[str, list[dict[str, Any]]]:
    stub = state.get("orchestrator_stub") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("retrieval") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    hits = await retrieve_context(q, top_k=5)
    return {"retrieval_hits": hits}


def build_query_graph() -> StateGraph:
    g: StateGraph = StateGraph(QueryGraphState)
    g.add_node("echo", echo_node)
    g.add_node("orchestrator_stub", orchestrator_stub_node)
    g.add_node("retrieve", retrieve_node)
    g.add_edge(START, "echo")
    g.add_edge("echo", "orchestrator_stub")
    g.add_edge("orchestrator_stub", "retrieve")
    g.add_edge("retrieve", END)
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
