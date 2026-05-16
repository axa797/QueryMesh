"""Google OAuth authorization code flow helpers (authorize URL, token exchange, id_token)."""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx
import jwt
from jwt import DecodeError, PyJWKClient

_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_jwks = PyJWKClient(_GOOGLE_JWKS)


def google_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
            "include_granted_scopes": "true",
        },
    )
    return f"{_GOOGLE_AUTHORIZE}?{q}"


async def exchange_google_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    ).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async def _post(client: httpx.AsyncClient) -> dict[str, Any]:
        resp = await client.post(_GOOGLE_TOKEN, content=data, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            raise ValueError("token response JSON must be an object")
        return body

    if http_client is not None:
        return await _post(http_client)

    async with httpx.AsyncClient(timeout=30.0) as client:
        return await _post(client)


def verify_google_id_token(*, raw_token: str, audience: str) -> dict[str, Any]:
    key = _jwks.get_signing_key_from_jwt(raw_token)
    try:
        decoded = jwt.decode(
            raw_token,
            key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_ISSUERS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except DecodeError:
        raise
    if not isinstance(decoded, dict):
        raise DecodeError("invalid payload")
    return decoded


def email_verified_claim(claims: dict[str, Any]) -> bool:
    v = claims.get("email_verified")
    if v is True:
        return True
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return False
