"""Code agent unit tests (mocked Vertex + E2B)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from agents import code_agent as ca


def test_run_code_generation_skips_exec_without_e2b(monkeypatch: pytest.MonkeyPatch) -> None:
    class _S:
        google_cloud_project = "p"
        vertex_llm_model = "gemini-2.0-flash"
        google_cloud_location = "us-central1"
        e2b_api_key = None

    monkeypatch.setattr(ca, "get_settings", lambda: _S())
    monkeypatch.setattr(
        ca,
        "_generate_code_sync",
        lambda **_: (
            '{"language":"python","code":"print(42)","explanation":"x",'
            '"dependencies":[],"notes":"","request_execution":true}'
        ),
    )
    monkeypatch.setattr(
        ca,
        "exec_python",
        AsyncMock(
            return_value={
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "source": "skipped_no_key",
            },
        ),
    )
    out = asyncio.run(ca.run_code_generation("run this"))
    assert out["source"] == "llm"
    assert out["code"] == "print(42)"
    assert out["execution"] is None
    ca.exec_python.assert_awaited_once()


def test_run_code_generation_no_vertex_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class _S:
        google_cloud_project = None

    monkeypatch.setattr(ca, "get_settings", lambda: _S())
    out = asyncio.run(ca.run_code_generation("any"))
    assert out["source"] == "fallback_no_vertex"
