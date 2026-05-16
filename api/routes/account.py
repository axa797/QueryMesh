"""Google OAuth signup/login and API key lifecycle (portal JWT unchanged for /chat)."""

from __future__ import annotations

import secrets
import urllib.parse
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from memory.session import session_scope

from api.account_portal import (
    insert_api_key_row,
    list_api_keys_for_user,
    revoke_api_key,
    upsert_user_from_google,
)
from api.auth import digest_api_key
from api.deps import PortalUserId
from api.google_oauth import (
    email_verified_claim,
    exchange_google_authorization_code,
    google_authorization_url,
    verify_google_id_token,
)
from api.portal_jwt import issue_portal_token
from api.schemas.account import ApiKeyCreateResponse, ApiKeyListItem
from api.settings import Settings, get_settings

router = APIRouter(prefix="/account", tags=["account"])

OAUTH_STATE_COOKIE = "portal_oauth_state"


def _portal_secret_or_503() -> str:
    secret = (get_settings().portal_jwt_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "portal_disabled",
                "message": "Account portal is not configured (set PORTAL_JWT_SECRET).",
            },
        )
    return secret


def _google_oauth_config_or_503() -> tuple[str, str, str, str]:
    """Returns (client_id, client_secret, redirect_uri, portal_frontend_base_url)."""
    _portal_secret_or_503()
    s = get_settings()
    cid = (s.google_oauth_client_id or "").strip()
    csec = (s.google_oauth_client_secret or "").strip()
    redir = (s.google_oauth_redirect_uri or "").strip()
    front = (s.portal_frontend_base_url or "").strip()
    if not cid or not csec or not redir or not front:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "oauth_disabled",
                "message": (
                    "Google OAuth portal is not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
                    "GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI, and "
                    "PORTAL_FRONTEND_BASE_URL."
                ),
            },
        )
    return cid, csec, redir, front


def _oauth_callback_redirect(settings: Settings, fragment: str) -> RedirectResponse:
    base = (settings.portal_frontend_base_url or "").rstrip("/")
    target = urllib.parse.urljoin(base + "/", "oauth/callback")
    return RedirectResponse(f"{target}#{fragment}", status_code=302)


def _oauth_cookie_secure(redirect_uri: str) -> bool:
    return redirect_uri.lower().startswith("https://")


@router.get("/oauth/google/start")
async def oauth_google_start() -> RedirectResponse:
    client_id, _, redirect_uri, _ = _google_oauth_config_or_503()
    state = secrets.token_urlsafe(32)
    authorize = google_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
    )
    resp = RedirectResponse(authorize, status_code=302)
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        max_age=600,
        samesite="lax",
        secure=_oauth_cookie_secure(redirect_uri),
        path="/account/oauth/google",
    )
    return resp


@router.get("/oauth/google/callback")
async def oauth_google_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> RedirectResponse:
    client_id, client_secret, redirect_uri, _ = _google_oauth_config_or_503()
    settings = get_settings()

    def _frag_error(message: str) -> RedirectResponse:
        frag = urllib.parse.urlencode({"error": "oauth_failed", "error_description": message})
        resp = _oauth_callback_redirect(settings, frag)
        resp.delete_cookie(key=OAUTH_STATE_COOKIE, path="/account/oauth/google")
        return resp

    if error:
        msg = urllib.parse.unquote(error_description or error or "access_denied")
        return _frag_error(msg)

    ck = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state or not ck:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "oauth_state_missing",
                "message": "Missing OAuth state or cookie (start login from Continue with Google).",
            },
        )
    if not secrets.compare_digest(state, ck):
        raise HTTPException(
            status_code=400,
            detail={"error": "oauth_state_invalid", "message": "OAuth state mismatch (CSRF)."},
        )

    if not code:
        raise HTTPException(status_code=400, detail={"error": "oauth_code_missing"})

    try:
        tokens = await exchange_google_authorization_code(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
    except httpx.HTTPStatusError as exc:
        return _frag_error(f"token exchange failed: {exc.response.status_code}")
    except Exception as exc:  # noqa: BLE001 — user-facing SPA redirect
        return _frag_error(f"token exchange failed: {exc!s}")

    id_raw = tokens.get("id_token")
    if not isinstance(id_raw, str) or not id_raw:
        return _frag_error("missing id_token in token response")

    try:
        claims = verify_google_id_token(raw_token=id_raw, audience=client_id)
    except Exception:
        return _frag_error("invalid id_token")

    if not email_verified_claim(claims):
        return _frag_error("Google email is not verified")

    sub = claims.get("sub")
    email = claims.get("email")
    display_name = claims.get("name")
    if not isinstance(sub, str) or not sub:
        return _frag_error("missing sub in id_token")
    if not isinstance(email, str) or not email.strip():
        return _frag_error("missing email in id_token")

    name_claim: str | None = None
    if isinstance(display_name, str) and display_name.strip():
        name_claim = display_name.strip()

    secret = _portal_secret_or_503()
    try:
        async with session_scope() as session:
            uid = await upsert_user_from_google(session, email=email, google_sub=sub)
            tok = issue_portal_token(
                user_id=uid,
                secret=secret,
                ttl_hours=get_settings().portal_jwt_ttl_hours,
                email=email.strip(),
                name=name_claim,
            )
    except Exception as exc:
        return _frag_error(f"account error: {exc!s}")

    frag = urllib.parse.urlencode(
        {
            "access_token": tok,
            "token_type": "bearer",
        },
    )
    ok = _oauth_callback_redirect(settings, frag)
    ok.delete_cookie(key=OAUTH_STATE_COOKIE, path="/account/oauth/google")
    return ok


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
async def mint_api_key(user_id: PortalUserId) -> ApiKeyCreateResponse:
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    digest = digest_api_key(raw, settings.api_key_pepper)
    async with session_scope() as session:
        kid = await insert_api_key_row(session, user_id, digest)
    return ApiKeyCreateResponse(api_key=raw, key_id=kid)


@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_api_keys(user_id: PortalUserId) -> list[ApiKeyListItem]:
    async with session_scope() as session:
        rows = await list_api_keys_for_user(session, user_id)
    return [
        ApiKeyListItem(
            key_id=r["key_id"],
            created_at=r["created_at"],
            revoked_at=r["revoked_at"],
        )
        for r in rows
    ]


@router.post("/api-keys/{key_id}/revoke")
async def revoke_account_api_key(key_id: UUID, user_id: PortalUserId) -> dict[str, str]:
    async with session_scope() as session:
        ok = await revoke_api_key(session, user_id=user_id, key_id=key_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_key",
                "message": "API key not found or already revoked.",
            },
        )
    return {"status": "ok"}
