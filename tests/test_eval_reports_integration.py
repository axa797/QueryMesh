"""GET /eval-reports with Postgres (minted API key)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from api.settings import get_settings
from fastapi.testclient import TestClient
from memory.eval_report_store import insert_eval_report
from memory.session import reset_connection_pool

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


def test_eval_reports_list_and_detail() -> None:
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
    hdr = {"Authorization": f"Bearer {key}"}

    async def _seed() -> str:
        rid = await insert_eval_report(
            mode="golden (integration test)",
            n_samples=2,
            aggregate_metrics={"faithfulness": 0.9123},
            per_row_metrics=[
                {"golden_id": "row-1", "faithfulness": 0.9, "question_preview": "q?"},
                {"golden_id": "row-2", "faithfulness": 0.92},
            ],
            judge_model="gemini-integration",
            embedding_model="text-embedding-005",
            langfuse_trace_id="trace-test-xyz",
            trigger="ci",
            git_commit="deadbeef",
        )
        return str(rid)

    report_id = asyncio.run(_seed())

    from api.main import app

    with TestClient(app) as client:
        lst = client.get("/eval-reports?page=1&page_size=20", headers=hdr)
        assert lst.status_code == 200
        body = lst.json()
        assert body["total"] >= 1
        assert isinstance(body["items"], list)
        match = next((x for x in body["items"] if x["id"] == report_id), None)
        assert match is not None
        assert match["aggregate_metrics"]["faithfulness"] == pytest.approx(0.9123)
        assert match["trigger"] == "ci"
        assert match["langfuse_trace_id"] == "trace-test-xyz"

        detail = client.get(f"/eval-reports/{report_id}", headers=hdr)
        assert detail.status_code == 200
        d = detail.json()
        assert d["id"] == report_id
        assert len(d["per_row_metrics"]) == 2
        assert d["git_commit"] == "deadbeef"
        assert d["per_row_metrics"][0]["golden_id"] == "row-1"

        missing = client.get("/eval-reports/00000000-0000-0000-0000-000000000099", headers=hdr)
        assert missing.status_code == 404
