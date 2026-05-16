"""Health readiness: status degraded when core deps are down."""

from __future__ import annotations

import pytest
from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


async def _ping_true(*_args, **_kwargs) -> bool:
    return True


async def _ping_false(*_args, **_kwargs) -> bool:
    return False


def test_health_ok_when_deps_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.main.ping_postgres", _ping_true)
    monkeypatch.setattr("api.main.ping_redis", _ping_true)
    monkeypatch.setattr("api.main.ping_qdrant", _ping_true)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["services"]["postgres"] is True
    assert body["services"]["redis"] is True


def test_health_degraded_when_postgres_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.main.ping_postgres", _ping_false)
    monkeypatch.setattr("api.main.ping_redis", _ping_true)
    monkeypatch.setattr("api.main.ping_qdrant", _ping_true)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["services"]["postgres"] is False


def test_user_facing_oauth_error_masks_connection_refused() -> None:
    from api.routes.account import _user_facing_oauth_error

    msg = _user_facing_oauth_error("[Errno 111] Connection refused")
    assert "111" not in msg
    assert "unavailable" in msg.lower()
