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
            None,
            uuid.uuid4(),
        )
    )
    assert "Cloud Run" in out["message"]
    assert out["memory_saved"] is False
    assert out["source"] == "fallback_no_gcp"


def test_finalize_strips_sources_section() -> None:
    blob = "- " + ("x " * 200)
    raw = "Short answer prose.\n\nSources:\n" + blob
    out = s.finalize_synthesis_display_message(raw)
    assert "Sources" not in out
    assert "Short answer" in out


def test_finalize_strips_skipped_rag_line() -> None:
    raw = "Retrieval was not routed for this query.\n\nVowel counts: a: 1"
    out = s.finalize_synthesis_display_message(raw)
    assert "not routed" not in out.lower()
    assert "Vowel" in out


def test_finalize_sources_only_returns_placeholder() -> None:
    raw = "Sources:\n- only bullets here\n- more"
    out = s.finalize_synthesis_display_message(raw)
    assert "below" in out.lower()


def test_mask_stream_partial_shows_stdout_while_provisional_rambles() -> None:
    assert s._mask_stream_partial_with_stdout("31", "Here is a long code block…") == "31"
    assert s._mask_stream_partial_with_stdout("31", "31") == "31"
    assert s._mask_stream_partial_with_stdout("31", "31\n\nOk.") == "31\n\nOk."
    assert s._mask_stream_partial_with_stdout("31", "3") == "3"
    assert s._mask_stream_partial_with_stdout(None, "anything") == "anything"


def test_parse_execution_stdout() -> None:
    assert s._parse_execution_stdout(None) is None
    assert s._parse_execution_stdout({"execution": {"stdout": " 42\n"}}) == "42"
