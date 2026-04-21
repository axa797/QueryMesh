"""HS256 JWT for browser / portal sessions (not used for POST /query API keys)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt


def issue_portal_token(*, user_id: UUID, secret: str, ttl_hours: int) -> str:
    if ttl_hours < 1:
        raise ValueError("ttl_hours must be >= 1")
    now = datetime.now(UTC)
    exp = now + timedelta(hours=ttl_hours)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": exp},
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
