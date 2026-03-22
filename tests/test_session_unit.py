"""Session envelope behavior with dependency overrides (no real Redis)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from api.deps import get_current_user_internal_id
from api.main import app
from fastapi.testclient import TestClient
from memory.redis_client import redis_dependency


class DictRedis:
    """Minimal async Redis stub."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)


@pytest.fixture
def fixed_user_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-bbbb-4ccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def client_with_session_deps(fixed_user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch):
    fake_redis = DictRedis()

    async def fake_load_top_k(*_args, **_kwargs):
        return []

    async def fake_compiled_graph():
        from graph.pipeline import build_query_graph
        from langgraph.checkpoint.memory import MemorySaver

        return build_query_graph().compile(checkpointer=MemorySaver())

    async def fake_route(_q: str, _mem: str) -> dict:
        return {
            "intents": ["retrieval"],
            "rewritten_queries": {"retrieval": _q or "q"},
            "parallel": False,
            "source": "test",
        }

    monkeypatch.setattr("api.routes.query.load_top_k_memories", fake_load_top_k)
    monkeypatch.setattr("api.routes.query.get_compiled_query_graph", fake_compiled_graph)
    monkeypatch.setattr("graph.pipeline.retrieve_context", AsyncMock(return_value=[]))
    monkeypatch.setattr("graph.pipeline.run_orchestrator", fake_route)

    async def user_override() -> uuid.UUID:
        return fixed_user_id

    async def redis_override():
        return fake_redis

    app.dependency_overrides[get_current_user_internal_id] = user_override
    app.dependency_overrides[redis_dependency] = redis_override
    yield TestClient(app), fake_redis
    app.dependency_overrides.clear()


def test_mints_session_when_omitted(
    client_with_session_deps: tuple[TestClient, DictRedis],
) -> None:
    client, fake = client_with_session_deps
    r = client.post("/query", json={"query": "hi"}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] != "stub"
    assert len(fake.store) == 1


def test_reuses_session(
    client_with_session_deps: tuple[TestClient, DictRedis],
) -> None:
    client, _fake = client_with_session_deps
    r1 = client.post("/query", json={"query": "a"}, headers={"Authorization": "Bearer x"})
    assert r1.status_code == 200
    sid = r1.json()["session_id"]
    r2 = client.post(
        "/query",
        json={"query": "b", "session_id": sid},
        headers={"Authorization": "Bearer x"},
    )
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid


def test_unknown_session_403(
    client_with_session_deps: tuple[TestClient, DictRedis],
) -> None:
    client, _fake = client_with_session_deps
    r = client.post(
        "/query",
        json={"query": "a", "session_id": str(uuid.uuid4())},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "invalid_session"


def test_malformed_session_id_403(
    client_with_session_deps: tuple[TestClient, DictRedis],
) -> None:
    client, _fake = client_with_session_deps
    r = client.post(
        "/query",
        json={"query": "a", "session_id": "not-a-uuid"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403
    assert r.json()["error"] == "invalid_session"


def test_other_users_session_403(
    client_with_session_deps: tuple[TestClient, DictRedis],
    fixed_user_id: uuid.UUID,
) -> None:
    client, _fake = client_with_session_deps
    r1 = client.post("/query", json={"query": "a"}, headers={"Authorization": "Bearer x"})
    sid = r1.json()["session_id"]

    other = uuid.UUID("bbbbbbbb-bbbb-4ccc-dddd-eeeeeeeeeeee")

    async def other_user() -> uuid.UUID:
        return other

    async def original_user() -> uuid.UUID:
        return fixed_user_id

    app.dependency_overrides[get_current_user_internal_id] = other_user
    try:
        r2 = client.post(
            "/query",
            json={"query": "b", "session_id": sid},
            headers={"Authorization": "Bearer x"},
        )
        assert r2.status_code == 403
        assert r2.json()["error"] == "invalid_session"
    finally:
        app.dependency_overrides[get_current_user_internal_id] = original_user
