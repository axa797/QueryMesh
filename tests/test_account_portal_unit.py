"""Portal helpers and disabled-portal behavior (no Postgres required)."""

from __future__ import annotations

import uuid

import pytest
from api.main import app
from api.passwords import hash_password, verify_password
from api.portal_jwt import decode_portal_sub, issue_portal_token
from api.settings import get_settings
from fastapi.testclient import TestClient


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)


def test_portal_jwt_roundtrip() -> None:
    uid = uuid.uuid4()
    secret = "unit-test-portal-secret-not-for-prod"
    tok = issue_portal_token(user_id=uid, secret=secret, ttl_hours=24)
    assert decode_portal_sub(token=tok, secret=secret) == uid


def test_register_returns_503_when_portal_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_JWT_SECRET", "")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.post(
            "/account/register",
            json={"email": "nobody@example.com", "password": "passworddd"},
        )
        assert r.status_code == 503
        assert r.json()["error"] == "portal_disabled"
    finally:
        get_settings.cache_clear()
