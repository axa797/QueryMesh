"""Account portal against Postgres (alembic revision 003_user_portal_login required).

Uses ``httpx.AsyncClient`` + ``ASGITransport`` so SQLAlchemy/asyncpg shares one event loop
(unlike ``TestClient``, which can bind the pool to different loops across requests).
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from api.main import app
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
    get_settings.cache_clear()
    reset_connection_pool()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    get_settings.cache_clear()
    reset_connection_pool()


@pytest.mark.asyncio
async def test_register_login_mint_list_revoke_portal(
    portal_http: httpx.AsyncClient,
) -> None:
    dsn = os.environ["DATABASE_URL"]
    email = f"acct_{uuid.uuid4().hex[:16]}@example.com"
    password = "integration-pass-9876"
    user_id: str | None = None
    try:
        r = await portal_http.post(
            "/account/register",
            json={"email": email, "password": password},
        )
        if r.status_code != 201:
            detail = r.json() if r.text else r.text
            pytest.fail(
                f"register failed {r.status_code}: {detail!r} "
                "(ensure `alembic upgrade head` applied, including 003_user_portal_login)",
            )
        body = r.json()
        portal_tok = body["access_token"]
        user_id = str(body["user_id"])

        r2 = await portal_http.post(
            "/account/login",
            json={"email": email, "password": password},
        )
        assert r2.status_code == 200

        r_bad = await portal_http.post(
            "/account/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert r_bad.status_code == 401

        h = {"Authorization": f"Bearer {portal_tok}"}
        r3 = await portal_http.post("/account/api-keys", headers=h)
        assert r3.status_code == 200
        key_id = r3.json()["key_id"]

        r4 = await portal_http.get("/account/api-keys", headers=h)
        assert r4.status_code == 200
        ids = {row["key_id"] for row in r4.json()}
        assert key_id in ids

        r5 = await portal_http.post(f"/account/api-keys/{key_id}/revoke", headers=h)
        assert r5.status_code == 200

        r6 = await portal_http.get("/account/api-keys", headers=h)
        revoked = next(x for x in r6.json() if x["key_id"] == key_id)
        assert revoked["revoked_at"] is not None

        r_dup = await portal_http.post(
            "/account/register",
            json={"email": email, "password": "anotherpwd12"},
        )
        assert r_dup.status_code == 409
    finally:
        if user_id:
            await _cleanup_user(dsn, user_id)
