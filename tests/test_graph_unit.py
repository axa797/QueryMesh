"""LangGraph linear pipeline (in-memory checkpoints)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from graph.pipeline import build_query_graph
from langgraph.checkpoint.memory import MemorySaver


def test_echo_then_orchestrator_then_retrieve_linear() -> None:
    async def _run() -> None:
        orch_out = {
            "intents": ["retrieval"],
            "rewritten_queries": {"retrieval": "hello"},
            "parallel": False,
            "source": "test",
        }
        with patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=[])):
            with patch("graph.pipeline.run_orchestrator", new=AsyncMock(return_value=orch_out)):
                g = build_query_graph().compile(checkpointer=MemorySaver())
                out = await g.ainvoke(
                    {"query": "hello", "memory_compact": "prefers short answers"},
                    config={"configurable": {"thread_id": "user-1:session-1"}},
                )
                assert out["echo_reply"] == "echo:hello"
                assert out["orchestrator"]["source"] == "test"
                assert "retrieval" in out["orchestrator"]["intents"]
                assert out.get("retrieval_hits") == []

    asyncio.run(_run())
