"""Synthesizer offline path."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from agents import synthesizer as s


@pytest.fixture
def no_gcp(monkeypatch: pytest.MonkeyPatch):
    class _S:
        google_cloud_project = None
        vertex_llm_model = "gemini-2.0-flash"
        google_cloud_location = "us-central1"

    monkeypatch.setattr(s, "get_settings", lambda: _S())


def test_offline_synthesis(no_gcp: None) -> None:
    rag = {
        "answer": "Cloud Run scales.",
        "citations": [{"document": "run.pdf", "section": "Scaling"}],
        "confidence": "high",
    }
    out = asyncio.run(
        s.run_synthesizer(
            "how does run scale",
            "",
            {"intents": ["retrieval"], "rewritten_queries": {"retrieval": "x"}},
            rag,
            None,
            uuid.uuid4(),
        )
    )
    assert "Cloud Run" in out["message"]
    assert out["memory_saved"] is False
    assert out["source"] == "fallback_no_gcp"
