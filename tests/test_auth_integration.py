"""Auth + /query with real DB (mint script)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from api.settings import get_settings
from fastapi.testclient import TestClient
from memory.session import reset_connection_pool

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


def test_query_accepts_minted_key() -> None:
    url = os.environ.get("DATABASE_URL")
    pepper = os.environ.get("API_KEY_PEPPER")
    if not url or not pepper:
        pytest.skip("DATABASE_URL and API_KEY_PEPPER required")

    get_settings.cache_clear()
    reset_connection_pool()

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mint_api_key.py")],
        cwd=str(ROOT),
        env={
            **os.environ,
            "DATABASE_URL": url,
            "API_KEY_PEPPER": pepper,
            "PYTHONPATH": str(ROOT),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    key = proc.stdout.strip()

    from api.main import app

    client = TestClient(app)
    res = client.post(
        "/query",
        json={"query": "hello"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "response" in data
    assert "trace_id" in data
