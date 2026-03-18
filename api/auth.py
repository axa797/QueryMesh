"""Bearer API key → user id (spec §8)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def digest_api_key(raw_key: str, pepper: str) -> str:
    """HMAC-SHA256(api_key, pepper). The raw API key is the HMAC key."""
    return hmac.new(
        raw_key.encode("utf-8"),
        pepper.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def lookup_user_for_api_key(
    session: AsyncSession,
    raw_key: str,
    pepper: str,
) -> UUID | None:
    digest = digest_api_key(raw_key, pepper)
    result = await session.execute(
        text(
            "SELECT user_id::text AS user_id, key_digest FROM api_keys "
            "WHERE revoked_at IS NULL AND key_digest = :digest"
        ),
        {"digest": digest},
    )
    row = result.mappings().first()
    if row is None:
        return None
    if not secrets.compare_digest(row["key_digest"], digest):
        return None
    return UUID(row["user_id"])
