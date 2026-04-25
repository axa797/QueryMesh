"""LangGraph query pipeline: orchestration, optional parallel specialists, RAG, synthesis."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID

from agents.analytics_agent import run_analytics
from agents.code_agent import run_code_generation
from agents.orchestrator import run_orchestrator
from agents.rag_agent import run_rag_structured
from agents.synthesizer import run_synthesizer
from api.settings import get_settings
from langchain_core.messages import AIMessage, AnyMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph, add_messages
from memory.checkpointer import get_checkpoint_pool
from tools.retrieval_tool import retrieve_context
from typing_extensions import TypedDict

from graph.conversation import format_messages_compact, prior_messages_for_prompt

_compiled_lock = asyncio.Lock()
_compiled_graph: Any = None


class QueryGraphState(TypedDict, total=False):
    """Graph state: checkpointed messages + per-turn fields + node outputs."""

    user_id: str
    query: str
    memory_compact: str
    messages: Annotated[list[AnyMessage], add_messages]
    echo_reply: str
    orchestrator: dict[str, Any]
    retrieval_hits: list[dict[str, Any]]
    analytics_structured: dict[str, Any]
    code_structured: dict[str, Any]
    rag_structured: dict[str, Any]
    synthesis: dict[str, Any]


def _history_from_state(state: QueryGraphState) -> str:
    prior = prior_messages_for_prompt(state)
    cap = max(1, get_settings().graph_message_history_max)
    return format_messages_compact(prior, max_messages=cap)


def _intents(state: QueryGraphState) -> list[str]:
    orch = state.get("orchestrator") or {}
    raw = orch.get("intents") if isinstance(orch, dict) else None
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _parallel_specialists(orch: dict[str, Any] | None) -> bool:
    if not isinstance(orch, dict):
        return False
    return bool(orch.get("parallel"))


def echo_node(state: QueryGraphState) -> dict[str, str]:
    q = (state.get("query") or "").strip()
    return {"echo_reply": f"echo:{q[:2000]}"}


async def orchestrator_node(state: QueryGraphState) -> dict[str, dict[str, Any]]:
    history = _history_from_state(state)
    plan = await run_orchestrator(
        state.get("query") or "",
        state.get("memory_compact") or "",
        history,
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


def _skipped_analytics() -> dict[str, Any]:
    return {
        "analytics_structured": {
            "source": "skipped",
            "interpretation": "Analytics intent not selected for this query.",
        },
    }


def _skipped_code() -> dict[str, Any]:
    return {
        "code_structured": {
            "source": "skipped",
            "interpretation": "Code generation intent not selected for this query.",
        },
    }


async def _analytics_branch(state: QueryGraphState) -> dict[str, Any]:
    if "analytics" not in _intents(state):
        return _skipped_analytics()
    stub = state.get("orchestrator") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("analytics") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    ctx = _history_from_state(state)
    out = await run_analytics(q, ctx)
    return {"analytics_structured": out}


async def _code_branch(state: QueryGraphState) -> dict[str, Any]:
    if "code_generation" not in _intents(state):
        return _skipped_code()
    stub = state.get("orchestrator") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("code_generation") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    ctx = _history_from_state(state)
    out = await run_code_generation(q, ctx)
    return {"code_structured": out}


async def specialists_node(state: QueryGraphState) -> dict[str, Any]:
    """
    Run analytics and code agents — **in parallel** when orchestrator says ``parallel: true``
    and both intents are active (spec §6–7).
    """
    intents_s = set(_intents(state))
    orch = state.get("orchestrator") if isinstance(state.get("orchestrator"), dict) else {}
    orch = orch or {}
    need_a = "analytics" in intents_s
    need_c = "code_generation" in intents_s
    use_parallel = _parallel_specialists(orch) and need_a and need_c

    if use_parallel:
        a_part, c_part = await asyncio.gather(
            _analytics_branch(state),
            _code_branch(state),
        )
        return {**a_part, **c_part}

    merged: dict[str, Any] = {}
    merged.update(await _analytics_branch(state) if need_a else _skipped_analytics())
    merged.update(await _code_branch(state) if need_c else _skipped_code())
    return merged


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


async def synthesizer_node(state: QueryGraphState) -> dict[str, Any]:
    uid_s = (state.get("user_id") or "").strip()
    if not uid_s:
        raise ValueError("query graph state requires user_id")
    hist = _history_from_state(state)
    syn = await run_synthesizer(
        state.get("query") or "",
        state.get("memory_compact") or "",
        state.get("orchestrator") or {},
        state.get("rag_structured") or {},
        state.get("analytics_structured"),
        state.get("code_structured"),
        UUID(uid_s),
        hist,
    )
    msg_text = (syn.get("message") or "").strip()
    out: dict[str, Any] = {"synthesis": syn}
    if msg_text:
        out["messages"] = [AIMessage(content=msg_text)]
    return out


def build_query_graph() -> StateGraph:
    g: StateGraph = StateGraph(QueryGraphState)
    g.add_node("echo", echo_node)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("specialists", specialists_node)
    g.add_node("rag_structured", rag_structured_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_edge(START, "echo")
    g.add_edge("echo", "orchestrator")
    g.add_edge("orchestrator", "retrieve")
    g.add_edge("retrieve", "specialists")
    g.add_edge("specialists", "rag_structured")
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
