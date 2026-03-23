"""RAG structured JSON parsing."""

from __future__ import annotations

from agents import rag_agent as r


def test_parse_rag_json_roundtrip() -> None:
    raw = (
        '{"answer": "x", "citations": [{"document": "a.pdf", "section": "s"}], '
        '"confidence": "high"}'
    )
    out = r.parse_rag_json(raw)
    assert out["answer"] == "x"
    assert out["confidence"] == "high"
    assert len(out["citations"]) == 1


def test_fallback_when_no_hits() -> None:
    out = r._fallback_rag("q", [], source="t")
    assert out["confidence"] == "low"
    assert out["citations"] == []
