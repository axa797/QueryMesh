"""Langfuse config helper (no network)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from observability import instrumentation as lt


def test_build_config_no_callbacks_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:
        langfuse_public_key = None
        langfuse_secret_key = None
        langfuse_host = None

    monkeypatch.setattr(lt, "get_settings", lambda: S())
    cfg, trace_id = lt.build_langgraph_invoke_config(thread_id="t1", session_id="s1")
    assert "callbacks" not in cfg
    assert cfg["configurable"]["thread_id"] == "t1"
    assert len(trace_id) == 32


def test_build_config_with_keys_adds_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:
        langfuse_public_key = "pk-test"
        langfuse_secret_key = "sk-test"
        langfuse_host = None

    mock_lf = MagicMock()
    monkeypatch.setattr(lt, "get_settings", lambda: S())
    monkeypatch.setattr(lt, "Langfuse", mock_lf)
    cfg, trace_id = lt.build_langgraph_invoke_config(thread_id="t1", session_id="s1")
    assert "callbacks" in cfg
    assert len(cfg["callbacks"]) == 1
    assert cfg["metadata"]["langfuse_session_id"] == "s1"
    assert len(trace_id) == 32
    mock_lf.assert_called_once()
