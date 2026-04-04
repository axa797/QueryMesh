"""POST /ingest and GET /ingest/{job_id} (in-memory job store + stubbed runner)."""

from __future__ import annotations

import uuid

import pytest
from api.deps import get_current_user_internal_id, set_ingestion_job_repository_for_tests
from api.main import app
from fastapi.testclient import TestClient

from tests.ingestion_memory_repo import InMemoryIngestionJobRepository


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    uid = uuid.UUID("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb")
    repo = InMemoryIngestionJobRepository()
    set_ingestion_job_repository_for_tests(repo)

    async def user_override() -> uuid.UUID:
        return uid

    async def fake_run(job_id: str, source: str) -> None:
        await repo.mark_running(job_id=job_id)
        await repo.mark_succeeded(job_id=job_id, docs_indexed=9)

    app.dependency_overrides[get_current_user_internal_id] = user_override
    monkeypatch.setattr("api.ingestion_runner.run_ingestion_job", fake_run)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    set_ingestion_job_repository_for_tests(None)


def test_post_ingest_returns_job(
    auth_client: TestClient,
) -> None:
    r = auth_client.post("/ingest", json={"source": "gcp_docs"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "started"
    job_id = data["job_id"]
    st = auth_client.get(f"/ingest/{job_id}")
    assert st.status_code == 200
    body = st.json()
    assert body["status"] == "complete"
    assert body["docs_indexed"] == 9
    assert body["error"] is None


def test_get_unknown_job_404(auth_client: TestClient) -> None:
    r = auth_client.get(f"/ingest/{uuid.uuid4()}")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "unknown_job"


def test_other_users_job_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid.UUID("cccccccc-cccc-4ccc-cccc-cccccccccccc")
    other = uuid.UUID("dddddddd-dddd-4ddd-dddd-dddddddddddd")
    repo = InMemoryIngestionJobRepository()
    set_ingestion_job_repository_for_tests(repo)

    async def owner_user() -> uuid.UUID:
        return owner

    async def fake_run(job_id: str, source: str) -> None:
        await repo.mark_succeeded(job_id=job_id, docs_indexed=1)

    app.dependency_overrides[get_current_user_internal_id] = owner_user
    monkeypatch.setattr("api.ingestion_runner.run_ingestion_job", fake_run)
    try:
        with TestClient(app) as client:
            job_id = client.post("/ingest", json={"source": "gcp_docs"}).json()["job_id"]
    finally:
        app.dependency_overrides.clear()

    async def other_user() -> uuid.UUID:
        return other

    app.dependency_overrides[get_current_user_internal_id] = other_user
    try:
        with TestClient(app) as client:
            r = client.get(f"/ingest/{job_id}")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
        set_ingestion_job_repository_for_tests(None)


def test_ingest_requires_auth() -> None:
    set_ingestion_job_repository_for_tests(None)
    try:
        with TestClient(app) as client:
            r = client.post("/ingest", json={"source": "gcp_docs"})
    finally:
        set_ingestion_job_repository_for_tests(None)
    assert r.status_code == 401
