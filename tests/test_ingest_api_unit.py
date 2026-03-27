"""POST /ingest and GET /ingest/{job_id} (mocked runner)."""

from __future__ import annotations

import uuid

import pytest
from api import ingestion_jobs
from api.deps import get_current_user_internal_id
from api.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def auth_client() -> TestClient:
    uid = uuid.UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")

    async def user_override() -> uuid.UUID:
        return uid

    app.dependency_overrides[get_current_user_internal_id] = user_override
    ingestion_jobs.reset_jobs_for_tests()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    ingestion_jobs.reset_jobs_for_tests()


def test_post_ingest_returns_job(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _stub(job_id: str, source: str) -> None:
        ingestion_jobs.job_succeed(job_id, 9)

    monkeypatch.setattr("api.routes.ingest.run_ingestion_job", _stub)

    r = auth_client.post("/ingest", json={"source": "gcp_docs"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "started"
    job_id = data["job_id"]
    st = auth_client.get(f"/ingest/{job_id}")
    assert st.status_code == 200
    assert st.json() == {"status": "complete", "docs_indexed": 9, "error": None}


def test_get_unknown_job_404(auth_client: TestClient) -> None:
    r = auth_client.get(f"/ingest/{uuid.uuid4()}")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "unknown_job"


def test_ingest_requires_auth() -> None:
    ingestion_jobs.reset_jobs_for_tests()
    with TestClient(app) as client:
        r = client.post("/ingest", json={"source": "gcp_docs"})
    assert r.status_code == 401
