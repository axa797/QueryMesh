"""Session envelope behavior with dependency overrides (no real Redis)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from api.deps import get_current_user_internal_id
from api.main import app
from fastapi.testclient import TestClient
from memory.redis_client import redis_dependency
from memory.session_envelope import thread_id_for


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

    async def fake_rag(_q: str, _hits: list) -> dict:
        return {
            "answer": "stub",
            "citations": [],
            "confidence": "low",
            "source": "test",
        }

    async def fake_synth(*_a, **_kw) -> dict:
        return {
            "message": "stub reply",
            "memory_saved": False,
            "memory_id": None,
            "source": "test",
        }

    monkeypatch.setattr("graph.pipeline.run_rag_structured", fake_rag)
    monkeypatch.setattr("graph.pipeline.run_synthesizer", fake_synth)

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
    data = r.json()
    assert data["error"] == "invalid_session"
    assert data["message"] == "Session is unknown or does not belong to this API key."


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


def test_langgraph_config_thread_id_matches_spec(
    fixed_user_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate (a): thread_id passed to LangGraph is user_internal_id:session_id (spec §7)."""
    captured: dict = {}

    async def fake_load_top_k(*_a, **_kw):
        return []

    class FakeGraph:
        async def ainvoke(self, _state, config=None):
            captured["config"] = config
            return {
                "echo_reply": None,
                "orchestrator": None,
                "retrieval_hits": None,
                "analytics_structured": None,
                "code_structured": None,
                "rag_structured": None,
                "synthesis": None,
            }

    async def fake_get_graph():
        return FakeGraph()

    fake_redis = DictRedis()

    monkeypatch.setattr("api.routes.query.load_top_k_memories", fake_load_top_k)
    monkeypatch.setattr("api.routes.query.get_compiled_query_graph", fake_get_graph)

    async def user_override() -> uuid.UUID:
        return fixed_user_id

    async def redis_override():
        return fake_redis

    app.dependency_overrides[get_current_user_internal_id] = user_override
    app.dependency_overrides[redis_dependency] = redis_override
    try:
        with TestClient(app) as client:
            r = client.post("/query", json={"query": "hi"}, headers={"Authorization": "Bearer x"})
            assert r.status_code == 200
        sid = uuid.UUID(r.json()["session_id"])
        expected_tid = thread_id_for(fixed_user_id, sid)
        cfg = captured.get("config") or {}
        assert cfg.get("configurable", {}).get("thread_id") == expected_tid
        assert cfg.get("metadata", {}).get("thread_id") == expected_tid
    finally:
        app.dependency_overrides.clear()
