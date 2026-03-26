"""POST /query rate limit (Phase 14)."""

from __future__ import annotations

import pytest
from api.main import app
from api.settings import get_settings
from fastapi.testclient import TestClient


@pytest.fixture
def low_query_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUERY_RATE_LIMIT", "2/minute")
    get_settings.cache_clear()
    yield
    try:
        from api.rate_limit import limiter

        limiter.reset()
    except (NotImplementedError, AttributeError):
        pass


def test_rate_limit_before_auth_returns_429(low_query_rate_limit: None) -> None:
    """Unauthenticated /query still consumes the per-client bucket (IP fallback key)."""
    with TestClient(app) as client:
        r1 = client.post("/query", json={"query": "a"})
        r2 = client.post("/query", json={"query": "b"})
        r3 = client.post("/query", json={"query": "c"})
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 429
    body = r3.json()
    assert body["error"] == "rate_limit_exceeded"
    assert "message" in body
    assert "2/minute" in body["message"]


def test_health_not_rate_limited(low_query_rate_limit: None) -> None:
    with TestClient(app) as client:
        for _ in range(5):
            r = client.get("/health")
            assert r.status_code == 200
