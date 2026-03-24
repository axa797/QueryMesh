"""Analytics agent without GCP."""

from __future__ import annotations

import asyncio

import pytest
from agents import analytics_agent as aa


@pytest.fixture
def no_settings(monkeypatch: pytest.MonkeyPatch):
    class _S:
        google_cloud_project = None
        bigquery_project_id = None
        bigquery_dataset = "querymesh"
        vertex_llm_model = "gemini-2.0-flash"
        google_cloud_location = "us-central1"

    monkeypatch.setattr(aa, "get_settings", lambda: _S())


def test_run_analytics_without_bq_project(no_settings: None) -> None:
    out = asyncio.run(aa.run_analytics("how many rows"))
    assert out["source"] == "fallback_no_bq"
    assert out["row_count"] == 0
