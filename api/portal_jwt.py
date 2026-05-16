"""HS256 JWT for browser / portal sessions (not used for POST /query API keys)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt


def issue_portal_token(
    *,
    user_id: UUID,
    secret: str,
    ttl_hours: int,
    email: str | None = None,
    name: str | None = None,
) -> str:
    if ttl_hours < 1:
        raise ValueError("ttl_hours must be >= 1")
    now = datetime.now(UTC)
    exp = now + timedelta(hours=ttl_hours)
    payload: dict[str, object] = {"sub": str(user_id), "iat": now, "exp": exp}
    if email and str(email).strip():
        payload["email"] = str(email).strip()
    if name and str(name).strip():
        payload["name"] = str(name).strip()
    return jwt.encode(
        payload,
        secret,
        algorithm="HS256",
    )


def decode_portal_sub(*, token: str, secret: str) -> UUID:
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    return UUID(str(payload["sub"]))
