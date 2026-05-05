"""Conversation memory via LangGraph ``messages`` + checkpointer (not Redis)."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from graph.pipeline import build_query_graph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def test_second_turn_orchestrator_sees_prior_turns_in_history() -> None:
    history_seen: list[str] = []

    async def record_orch(q: str, mem: str, hist: str) -> dict:
        history_seen.append(hist)
        return {
            "intents": ["retrieval"],
            "rewritten_queries": {"retrieval": q or "q"},
            "parallel": False,
            "source": "test",
        }

    async def _run() -> None:
        uid = str(uuid.uuid4())
        thread = f"{uid}:session-a"
        g = build_query_graph().compile(checkpointer=MemorySaver())
        cfg = {"configurable": {"thread_id": thread}}
        rag_out = {
            "answer": "stub",
            "citations": [],
            "confidence": "low",
            "source": "test",
        }
        syn1 = {
            "message": "Nice to meet you, Kurzaar.",
            "memory_saved": False,
            "memory_id": None,
            "source": "test",
        }
        with (
            patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=([], {}))),
            patch("graph.pipeline.run_orchestrator", new=record_orch),
            patch("graph.pipeline.run_rag_structured", new=AsyncMock(return_value=rag_out)),
            patch("graph.pipeline.run_synthesizer", new=AsyncMock(return_value=syn1)),
        ):
            await g.ainvoke(
                {
                    "user_id": uid,
                    "query": "My name is Kurzaar",
                    "memory_compact": "",
                    "messages": [HumanMessage(content="My name is Kurzaar")],
                },
                config=cfg,
            )

        assert history_seen[0] == ""

        syn2 = {
            "message": "Your name is Kurzaar.",
            "memory_saved": False,
            "memory_id": None,
            "source": "test",
        }
        with (
            patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=([], {}))),
            patch("graph.pipeline.run_orchestrator", new=record_orch),
            patch("graph.pipeline.run_rag_structured", new=AsyncMock(return_value=rag_out)),
            patch("graph.pipeline.run_synthesizer", new=AsyncMock(return_value=syn2)),
        ):
            await g.ainvoke(
                {
                    "user_id": uid,
                    "query": "What is my name?",
                    "memory_compact": "",
                    "messages": [HumanMessage(content="What is my name?")],
                },
                config=cfg,
            )

        assert len(history_seen) == 2
        assert "Kurzaar" in history_seen[1]

    asyncio.run(_run())
