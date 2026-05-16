"""Portal helpers and OAuth routes (no Postgres required for OAuth start / CSRF)."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from api.main import app
from api.portal_jwt import decode_portal_sub, issue_portal_token
from api.settings import get_settings
from fastapi.testclient import TestClient


def test_portal_jwt_roundtrip() -> None:
    uid = uuid.uuid4()
    secret = "unit-test-portal-secret-not-for-prod"
    tok = issue_portal_token(user_id=uid, secret=secret, ttl_hours=24)
    assert decode_portal_sub(token=tok, secret=secret) == uid


def _oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORTAL_JWT_SECRET", "oauth-unit-portal-secret-32-char!!")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "unit-test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "unit-test-client-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/account/oauth/google/callback",
    )
    monkeypatch.setenv("PORTAL_FRONTEND_BASE_URL", "http://127.0.0.1:3000")


def test_oauth_google_start_returns_503_when_portal_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PORTAL_JWT_SECRET", "")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.get("/account/oauth/google/start", follow_redirects=False)
        assert r.status_code == 503
        assert r.json()["error"] == "portal_disabled"
    finally:
        get_settings.cache_clear()


def test_oauth_google_start_returns_503_when_google_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PORTAL_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.get("/account/oauth/google/start", follow_redirects=False)
        assert r.status_code == 503
        assert r.json()["error"] == "oauth_disabled"
    finally:
        get_settings.cache_clear()


def test_google_oauth_start_redirect_sets_state_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    _oauth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r = client.get("/account/oauth/google/start", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://accounts.google.com/")
        qs = parse_qs(urlparse(loc).query)
        scopes = qs.get("scope", [""])[0]
        assert all(s in scopes for s in ("openid", "email", "profile"))
        st = qs.get("state", [None])[0]
        assert st is not None and len(st) > 8
        ck = r.headers.get("set-cookie", "").lower()
        assert "portal_oauth_state=" in ck
        assert "httponly" in ck
    finally:
        get_settings.cache_clear()


def test_oauth_google_callback_state_mismatch_is_400(monkeypatch: pytest.MonkeyPatch) -> None:
    _oauth_env(monkeypatch)
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        r0 = client.get("/account/oauth/google/start", follow_redirects=False)
        assert r0.status_code == 302
        st = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
        r1 = client.get(
            "/account/oauth/google/callback",
            params={"code": "fake", "state": st + "!"},
            follow_redirects=False,
        )
        assert r1.status_code == 400
        assert r1.json()["error"] == "oauth_state_invalid"
    finally:
        get_settings.cache_clear()
