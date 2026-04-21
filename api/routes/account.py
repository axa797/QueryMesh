"""Browser-friendly signup/login and API key lifecycle (spec §8 API keys unchanged for /query)."""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException
from memory.session import session_scope

from api.account_portal import (
    DuplicatePortalEmailError,
    fetch_login_row,
    insert_api_key_row,
    list_api_keys_for_user,
    revoke_api_key,
    safe_insert_portal_user,
)
from api.auth import digest_api_key
from api.deps import PortalUserId
from api.passwords import hash_password, verify_password
from api.portal_jwt import issue_portal_token
from api.schemas.account import (
    ApiKeyCreateResponse,
    ApiKeyListItem,
    LoginRequest,
    PortalTokenResponse,
    RegisterRequest,
)
from api.settings import get_settings

router = APIRouter(prefix="/account", tags=["account"])


def _portal_secret_or_503() -> str:
    settings = get_settings()
    secret = (settings.portal_jwt_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "portal_disabled",
                "message": "Account portal is not configured (set PORTAL_JWT_SECRET).",
            },
        )
    return secret


@router.post("/register", response_model=PortalTokenResponse, status_code=201)
async def register_account(body: RegisterRequest) -> PortalTokenResponse:
    secret = _portal_secret_or_503()
    settings = get_settings()
    email = body.email.strip().lower()
    ph = hash_password(body.password)
    try:
        async with session_scope() as session:
            uid = await safe_insert_portal_user(session, email, ph)
    except DuplicatePortalEmailError:
        raise HTTPException(
            status_code=409,
            detail={"error": "email_taken", "message": "Email already registered."},
        ) from None
    tok = issue_portal_token(
        user_id=uid,
        secret=secret,
        ttl_hours=settings.portal_jwt_ttl_hours,
    )
    return PortalTokenResponse(access_token=tok, user_id=uid)


@router.post("/login", response_model=PortalTokenResponse)
async def login_account(body: LoginRequest) -> PortalTokenResponse:
    secret = _portal_secret_or_503()
    settings = get_settings()
    email = body.email.strip().lower()
    async with session_scope() as session:
        row = await fetch_login_row(session, email)
    if row is None or not verify_password(body.password, row[1]):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_credentials",
                "message": "Invalid email or password.",
            },
        )
    uid = row[0]
    tok = issue_portal_token(
        user_id=uid,
        secret=secret,
        ttl_hours=settings.portal_jwt_ttl_hours,
    )
    return PortalTokenResponse(access_token=tok, user_id=uid)


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
