"""Auth + /query with real DB (mint script)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from api.settings import get_settings
from fastapi.testclient import TestClient
from memory.session import reset_connection_pool

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


def test_query_accepts_minted_key() -> None:
    url = os.environ.get("DATABASE_URL")
    pepper = os.environ.get("API_KEY_PEPPER")
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    if not url or not pepper:
        pytest.skip("DATABASE_URL and API_KEY_PEPPER required")

    os.environ["REDIS_URL"] = redis_url
    get_settings.cache_clear()
    reset_connection_pool()

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mint_api_key.py")],
        cwd=str(ROOT),
        env={
            **os.environ,
            "DATABASE_URL": url,
            "API_KEY_PEPPER": pepper,
            "REDIS_URL": redis_url,
            "PYTHONPATH": str(ROOT),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    key = proc.stdout.strip()

    from api.main import app

    orch_mock = AsyncMock(
        return_value={
            "intents": ["retrieval"],
            "rewritten_queries": {"retrieval": "hello"},
            "parallel": False,
            "source": "test",
        }
    )
    with patch("graph.pipeline.retrieve_context", new=AsyncMock(return_value=[])):
        with patch("graph.pipeline.run_orchestrator", new=orch_mock):
            with TestClient(app) as client:
                res = client.post(
                    "/query",
                    json={"query": "hello"},
                    headers={"Authorization": f"Bearer {key}"},
                )
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert "trace_id" in data
    assert "session_id" in data
    assert data["session_id"] != "stub"
