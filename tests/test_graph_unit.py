"""LangGraph pipeline through offline RAG + synthesizer (in-memory checkpoints)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from graph.pipeline import build_query_graph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def test_full_linear_pipeline_mocked_llm_steps() -> None:
    async def _run() -> None:
        uid = str(uuid.uuid4())
        orch_out = {
            "intents": ["retrieval"],
            "rewritten_queries": {"retrieval": "hello"},
            "parallel": False,
            "source": "test",
        }
        rag_out = {
            "answer": "dummy",
            "citations": [{"document": "d.pdf", "section": "s", "chunk_id": "0"}],
            "confidence": "low",
            "source": "test",
        }
        syn_out = {
            "message": "Hi",
            "memory_saved": False,
            "memory_id": None,
            "source": "test",
        }
        with (
            patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=([], {}))),
            patch(
                "graph.pipeline.run_orchestrator",
                new=AsyncMock(return_value=orch_out),
            ),
            patch(
                "graph.pipeline.run_rag_structured",
                new=AsyncMock(return_value=rag_out),
            ),
            patch(
                "graph.pipeline.run_synthesizer",
                new=AsyncMock(return_value=syn_out),
            ),
        ):
            g = build_query_graph().compile(checkpointer=MemorySaver())
            out = await g.ainvoke(
                {
                    "user_id": uid,
                    "query": "hello",
                    "memory_compact": "prefers short answers",
                    "messages": [HumanMessage(content="hello")],
                },
                config={"configurable": {"thread_id": "user-1:session-1"}},
            )
            assert out["echo_reply"] == "echo:hello"
            assert out["orchestrator"]["source"] == "test"
            assert out.get("retrieval_hits") == []
            assert out["rag_structured"]["answer"] == "dummy"
            assert out["code_structured"]["source"] == "skipped"
            assert out["synthesis"]["message"] == "Hi"

    asyncio.run(_run())
