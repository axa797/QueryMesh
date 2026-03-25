"""Parallel analytics + code fan-out when orchestrator.parallel is true."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from graph.pipeline import build_query_graph
from langgraph.checkpoint.memory import MemorySaver


def test_specialists_parallel_overlaps_execution() -> None:
    """When ``parallel: true`` and both intents fire, both agents should run concurrently."""

    async def _run() -> None:
        events: list[str] = []

        async def mock_analytics(*_a: object, **_kw: object) -> dict:
            events.append("a_start")
            await asyncio.sleep(0.08)
            events.append("a_end")
            return {"source": "llm", "interpretation": "x"}

        async def mock_code(*_a: object, **_kw: object) -> dict:
            events.append("c_start")
            await asyncio.sleep(0.08)
            events.append("c_end")
            return {"source": "llm", "interpretation": "y"}

        uid = str(uuid.uuid4())
        orch = {
            "intents": ["retrieval", "analytics", "code_generation"],
            "rewritten_queries": {
                "retrieval": "r",
                "analytics": "a",
                "code_generation": "c",
            },
            "parallel": True,
            "source": "test",
        }

        with (
            patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=[])),
            patch("graph.pipeline.run_orchestrator", new=AsyncMock(return_value=orch)),
            patch("graph.pipeline.run_analytics", new=mock_analytics),
            patch("graph.pipeline.run_code_generation", new=mock_code),
            patch(
                "graph.pipeline.run_rag_structured",
                new=AsyncMock(
                    return_value={
                        "answer": "ok",
                        "citations": [],
                        "confidence": "low",
                        "source": "test",
                    },
                ),
            ),
            patch(
                "graph.pipeline.run_synthesizer",
                new=AsyncMock(
                    return_value={
                        "message": "m",
                        "memory_saved": False,
                        "memory_id": None,
                        "source": "test",
                    },
                ),
            ),
        ):
            g = build_query_graph().compile(checkpointer=MemorySaver())
            await g.ainvoke(
                {"user_id": uid, "query": "q", "memory_compact": ""},
                config={"configurable": {"thread_id": "u:s"}},
            )

        # Parallel: code starts before analytics finishes.
        assert events.index("c_start") < events.index("a_end")

    asyncio.run(_run())


def test_specialists_sequential_runs_analytics_before_code() -> None:
    async def _run() -> None:
        events: list[str] = []

        async def mock_analytics(*_a: object, **_kw: object) -> dict:
            events.append("a_start")
            await asyncio.sleep(0.02)
            events.append("a_end")
            return {"source": "llm", "interpretation": "x"}

        async def mock_code(*_a: object, **_kw: object) -> dict:
            events.append("c_start")
            await asyncio.sleep(0.02)
            events.append("c_end")
            return {"source": "llm", "interpretation": "y"}

        uid = str(uuid.uuid4())
        orch = {
            "intents": ["retrieval", "analytics", "code_generation"],
            "rewritten_queries": {
                "retrieval": "r",
                "analytics": "a",
                "code_generation": "c",
            },
            "parallel": False,
            "source": "test",
        }

        with (
            patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=[])),
            patch("graph.pipeline.run_orchestrator", new=AsyncMock(return_value=orch)),
            patch("graph.pipeline.run_analytics", new=mock_analytics),
            patch("graph.pipeline.run_code_generation", new=mock_code),
            patch(
                "graph.pipeline.run_rag_structured",
                new=AsyncMock(
                    return_value={
                        "answer": "ok",
                        "citations": [],
                        "confidence": "low",
                        "source": "test",
                    },
                ),
            ),
            patch(
                "graph.pipeline.run_synthesizer",
                new=AsyncMock(
                    return_value={
                        "message": "m",
                        "memory_saved": False,
                        "memory_id": None,
                        "source": "test",
                    },
                ),
            ),
        ):
            g = build_query_graph().compile(checkpointer=MemorySaver())
            await g.ainvoke(
                {"user_id": uid, "query": "q", "memory_compact": ""},
                config={"configurable": {"thread_id": "u:s"}},
            )

        assert events.index("a_end") < events.index("c_start")

    asyncio.run(_run())
