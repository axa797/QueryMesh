"""Google OAuth portal against Postgres (alembic 006_google_oauth_sub recommended).

Uses ``httpx.AsyncClient`` + ``ASGITransport`` so SQLAlchemy/asyncpg shares one event loop
(unlike ``TestClient``, which can bind the pool to different loops across requests).
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest
from api.main import app
from api.portal_jwt import decode_portal_sub
from api.settings import get_settings
from memory.session import reset_connection_pool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def _cleanup_user(dsn: str, user_id: str) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM api_keys WHERE user_id = :u"), {"u": user_id})
            await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
    finally:
        await engine.dispose()


@pytest.fixture
async def portal_http(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    secret = (
        os.environ.get("PORTAL_JWT_SECRET", "").strip()
        or "integration-portal-test-secret-32chars-min!!"
    )
    monkeypatch.setenv("PORTAL_JWT_SECRET", secret)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "integration-test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "integration-test-client-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://test/account/oauth/google/callback",
    )
    monkeypatch.setenv("PORTAL_FRONTEND_BASE_URL", "http://frontend")

    exchange_mock = AsyncMock(return_value={"id_token": "stub.id.payload"})
    verify_mock = MagicMock()
    monkeypatch.setattr(
        "api.routes.account.exchange_google_authorization_code",
        exchange_mock,
    )
    monkeypatch.setattr(
        "api.routes.account.verify_google_id_token",
        verify_mock,
    )

    get_settings.cache_clear()
    reset_connection_pool()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        setattr(client, "_exchange_mock", exchange_mock)
        setattr(client, "_verify_mock", verify_mock)
        setattr(client, "_portal_secret", secret)
        yield client

    get_settings.cache_clear()
    reset_connection_pool()


@pytest.mark.asyncio
async def test_google_oauth_mint_api_key_flow(portal_http: httpx.AsyncClient) -> None:
    exchange_mock = portal_http._exchange_mock  # type: ignore[attr-defined]
    verify_mock = portal_http._verify_mock  # type: ignore[attr-defined]
    secret = portal_http._portal_secret  # type: ignore[attr-defined]

    dsn = os.environ["DATABASE_URL"]
    email = f"oauth_{uuid.uuid4().hex[:16]}@example.com"

    def _claims(*_: object, **__: object) -> dict[str, object]:
        return {
            "sub": f"go_{uuid.uuid4().hex[:20]}",
            "email": email,
            "email_verified": True,
        }

    uid_str: str | None = None
    verify_mock.side_effect = _claims
    try:
        r_start = await portal_http.get("/account/oauth/google/start", follow_redirects=False)
        assert r_start.status_code == 302
        query_state = parse_qs(urlparse(r_start.headers["location"]).query)["state"][0]

        r_cb = await portal_http.get(
            "/account/oauth/google/callback",
            params={"code": "auth-code-integration", "state": query_state},
            follow_redirects=False,
        )
        assert r_cb.status_code == 302
        loc = r_cb.headers["location"]
        assert loc.startswith("http://frontend/oauth/callback")
        fragment = urlparse(loc).fragment
        assert "access_token=" in fragment
        params_frag = dict(parse_qsl(fragment))
        portal_tok = params_frag["access_token"]
        uid = decode_portal_sub(token=portal_tok, secret=secret)
        uid_str = str(uid)

        assert exchange_mock.await_count >= 1
        kw = exchange_mock.await_args.kwargs if exchange_mock.await_args else {}
        assert kw.get("redirect_uri") == "http://test/account/oauth/google/callback"

        mint_h = {"Authorization": f"Bearer {portal_tok}"}
        r_key = await portal_http.post("/account/api-keys", headers=mint_h)
        assert r_key.status_code == 200
        key_id = r_key.json()["key_id"]

        r_list = await portal_http.get("/account/api-keys", headers=mint_h)
        ids = {row["key_id"] for row in r_list.json()}
        assert key_id in ids

        r_rev = await portal_http.post(f"/account/api-keys/{key_id}/revoke", headers=mint_h)
        assert r_rev.status_code == 200
    finally:
        if uid_str:
            await _cleanup_user(dsn, uid_str)
