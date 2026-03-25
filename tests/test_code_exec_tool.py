"""Unit tests for E2B wrapper (no real sandboxes)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from e2b.exceptions import TimeoutException
from tools import code_exec_tool as cet


def test_cap_combined_output_within_budget() -> None:
    assert cet.cap_combined_output("hi", "there", 100) == ("hi", "there")


def test_cap_combined_output_truncates() -> None:
    out, err = cet.cap_combined_output("x" * 1000, "y" * 1000, 50)
    total = len(out.encode()) + len(err.encode())
    assert total <= 50 + len(cet._TRUNC.encode()) + len(cet._TRUNC.encode())
    assert cet._TRUNC in (out + err)


def test_exec_python_skips_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:
        e2b_api_key = None

    monkeypatch.setattr(cet, "get_settings", lambda: S())
    monkeypatch.setattr(cet, "_exec_sem", None)
    r = asyncio.run(cet.exec_python("print(1)"))
    assert r["source"] == "skipped_no_key"


def test_exec_python_maps_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class S:
        e2b_api_key = "fake"
        e2b_template_id = "t"
        e2b_sandbox_timeout_seconds = 120
        code_exec_wall_seconds = 15.0
        code_exec_output_max_bytes = 65536
        code_exec_max_concurrent = 2
        code_exec_max_code_chars = 200_000

    class _SB:
        files = SimpleNamespace(write=AsyncMock())
        commands = SimpleNamespace(
            run=AsyncMock(side_effect=TimeoutException("execution timeout")),
        )

        async def __aenter__(self) -> _SB:
            return self

        async def __aexit__(self, *a: object) -> None:
            return None

    class _AS:
        @staticmethod
        async def create(**_kwargs: object) -> _SB:
            return _SB()

    monkeypatch.setattr(cet, "get_settings", lambda: S())
    monkeypatch.setattr(cet, "_exec_sem", None)
    monkeypatch.setattr(cet, "AsyncSandbox", _AS)
    r = asyncio.run(cet.exec_python("print(1)"))
    assert r["source"] == "e2b_timeout"
    assert "timeout" in (r.get("stderr") or "").lower()
