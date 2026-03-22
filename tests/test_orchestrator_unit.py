"""Orchestrator parsing and fallbacks (no Vertex calls)."""

from __future__ import annotations

import asyncio

import pytest
from agents import orchestrator as orch


def test_parse_route_json_strips_fences_and_caps_intents():
    raw = """```json
{"intents": ["retrieval", "retrieval", "analytics", "code_generation", "retrieval"],
 "rewritten_queries": {"retrieval": "r1", "analytics": ""},
 "parallel": true}
```"""
    out = orch.parse_route_json(raw, "user q", source="llm")
    assert out["source"] == "llm"
    assert out["intents"] == ["retrieval", "analytics", "code_generation"]
    assert out["rewritten_queries"]["retrieval"] == "r1"
    assert out["rewritten_queries"]["analytics"] == "user q"
    assert out["rewritten_queries"]["code_generation"] == "user q"
    assert out["parallel"] is True


def test_rag_fallback_route():
    out = orch.rag_fallback_route("  what is GKE  ", source="fallback_parse")
    assert out["intents"] == ["retrieval"]
    assert out["rewritten_queries"]["retrieval"] == "what is GKE"
    assert out["source"] == "fallback_parse"


def test_run_orchestrator_without_gcp_project(monkeypatch: pytest.MonkeyPatch):
    class _S:
        google_cloud_project = None
        vertex_llm_model = "gemini-2.0-flash"
        google_cloud_location = "us-central1"

    monkeypatch.setattr(orch, "get_settings", lambda: _S())
    out = asyncio.run(orch.run_orchestrator("hello", ""))
    assert out["source"] == "fallback_no_gcp"
    assert "retrieval" in out["intents"]
