"""LangGraph query pipeline: orchestration, optional parallel specialists, RAG, synthesis."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
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
from langgraph.config import get_config, get_stream_writer
from langgraph.graph import END, START, StateGraph, add_messages
from memory.checkpointer import get_checkpoint_pool
from tools.retrieval_tool import retrieve_context
from typing_extensions import TypedDict

from graph.conversation import format_messages_compact, prior_messages_for_prompt
from graph.source_cards import compact_sources_from_hits

_compiled_lock = asyncio.Lock()
_compiled_graph: Any = None


def merge_pipeline_metrics(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


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
    pipeline_metrics: Annotated[dict[str, Any], merge_pipeline_metrics]


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
    t0 = time.monotonic()
    plan = await run_orchestrator(
        state.get("query") or "",
        state.get("memory_compact") or "",
        history,
    )
    orch_ms = max(0, int((time.monotonic() - t0) * 1000))
    return {"orchestrator": plan, "pipeline_metrics": {"orchestrator_ms": orch_ms}}


async def retrieve_node(state: QueryGraphState) -> dict[str, Any]:
    if "retrieval" not in _intents(state):
        return {"retrieval_hits": [], "pipeline_metrics": {"retrieval_skipped": True}}
    stub = state.get("orchestrator") or {}
    rq = stub.get("rewritten_queries") if isinstance(stub, dict) else None
    rewritten = ""
    if isinstance(rq, dict):
        rewritten = (rq.get("retrieval") or "").strip()
    q = rewritten or (state.get("query") or "").strip()
    hits, retr_meta = await retrieve_context(q, top_k=5)
    return {"retrieval_hits": hits, "pipeline_metrics": dict(retr_meta)}


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

    t0 = time.monotonic()
    if use_parallel:
        a_part, c_part = await asyncio.gather(
            _analytics_branch(state),
            _code_branch(state),
        )
        elapsed = max(0, int((time.monotonic() - t0) * 1000))
        return {
            **a_part,
            **c_part,
            "pipeline_metrics": {"specialists_ms": elapsed},
        }

    merged: dict[str, Any] = {}
    merged.update(await _analytics_branch(state) if need_a else _skipped_analytics())
    merged.update(await _code_branch(state) if need_c else _skipped_code())
    elapsed = max(0, int((time.monotonic() - t0) * 1000))
    merged["pipeline_metrics"] = {"specialists_ms": elapsed}
    return merged


async def rag_structured_node(state: QueryGraphState) -> dict[str, Any]:
    if "retrieval" not in _intents(state):
        return {
            "rag_structured": {
                "answer": "Retrieval was not routed for this query.",
                "citations": [],
                "confidence": "low",
                "source": "skipped",
            },
            "pipeline_metrics": {"rag_structured_skipped": True},
        }
    t0 = time.monotonic()
    rag = await run_rag_structured(
        state.get("query") or "",
        state.get("retrieval_hits") or [],
    )
    rag_ms = max(0, int((time.monotonic() - t0) * 1000))
    return {"rag_structured": rag, "pipeline_metrics": {"rag_structured_ms": rag_ms}}


def _synthesis_partial_channel() -> Callable[[str], None] | None:
    """When ``POST /query/stream`` sets configurable ``stream_synthesis``, stream JSON ``message``.

    Writes LangGraph ``custom`` stream parts picked up alongside ``updates`` during ``astream``.
    """
    cfg = get_config()
    enabled = bool((cfg.get("configurable") or {}).get("stream_synthesis"))
    if not enabled:
        return None

    writer = get_stream_writer()
    last_seen = [""]

    def sink(msg: str) -> None:
        if msg == last_seen[0]:
            return
        last_seen[0] = msg
        writer({"type": "assistant_partial", "message": msg})

    return sink


async def synthesizer_node(state: QueryGraphState) -> dict[str, Any]:
    uid_s = (state.get("user_id") or "").strip()
    if not uid_s:
        raise ValueError("query graph state requires user_id")
    hist = _history_from_state(state)
    t0 = time.monotonic()
    synth_sink = _synthesis_partial_channel()
    syn = await run_synthesizer(
        state.get("query") or "",
        state.get("memory_compact") or "",
        state.get("orchestrator") or {},
        state.get("rag_structured") or {},
        state.get("analytics_structured"),
        state.get("code_structured"),
        UUID(uid_s),
        hist,
        synthesis_partial_sink=synth_sink,
    )
    synth_ms = max(0, int((time.monotonic() - t0) * 1000))
    msg_text = (syn.get("message") or "").strip()
    hits_raw = state.get("retrieval_hits") or []
    hits_list = [h for h in hits_raw if isinstance(h, dict)] if isinstance(hits_raw, list) else []
    cards = compact_sources_from_hits(hits_list)

    out: dict[str, Any] = {
        "synthesis": syn,
        "pipeline_metrics": {"synthesizer_ms": synth_ms},
    }
    if msg_text:
        kwargs: dict[str, Any] = {}
        if cards:
            kwargs["additional_kwargs"] = {"source_cards": cards}
        out["messages"] = [AIMessage(content=msg_text, **kwargs)]
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
