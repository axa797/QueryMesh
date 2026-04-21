"""Postgres helpers: portal users and API keys (same tables as mint script)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_portal_user(session: AsyncSession, email: str, password_hash: str) -> UUID:
    res = await session.execute(
        text(
            """
            INSERT INTO users (email, password_hash)
            VALUES (:email, :ph)
            RETURNING id
            """
        ),
        {"email": email, "ph": password_hash},
    )
    return res.scalar_one()


async def fetch_login_row(
    session: AsyncSession,
    email: str,
) -> tuple[UUID, str] | None:
    res = await session.execute(
        text(
            """
            SELECT id::text, password_hash
            FROM users
            WHERE email = :email AND password_hash IS NOT NULL
            """
        ),
        {"email": email},
    )
    row = res.mappings().first()
    if row is None:
        return None
    ph = row["password_hash"]
    if not ph:
        return None
    return UUID(row["id"]), str(ph)


async def insert_api_key_row(
    session: AsyncSession,
    user_id: UUID,
    key_digest: str,
) -> UUID:
    res = await session.execute(
        text(
            """
            INSERT INTO api_keys (user_id, key_digest)
            VALUES (:uid, :digest)
            RETURNING id
            """
        ),
        {"uid": user_id, "digest": key_digest},
    )
    return res.scalar_one()


async def list_api_keys_for_user(session: AsyncSession, user_id: UUID) -> list[dict[str, object]]:
    res = await session.execute(
        text(
            """
            SELECT id::text AS id, created_at, revoked_at
            FROM api_keys
            WHERE user_id = :uid
            ORDER BY created_at DESC
            """
        ),
        {"uid": user_id},
    )
    out: list[dict[str, object]] = []
    for row in res.mappings().all():
        out.append(
            {
                "key_id": UUID(str(row["id"])),
                "created_at": row["created_at"],
                "revoked_at": row["revoked_at"],
            },
        )
    return out


async def revoke_api_key(
    session: AsyncSession,
    *,
    user_id: UUID,
    key_id: UUID,
) -> bool:
    res = await session.execute(
        text(
            """
            UPDATE api_keys
            SET revoked_at = NOW()
            WHERE id = :kid AND user_id = :uid AND revoked_at IS NULL
            RETURNING id
            """
        ),
        {"kid": key_id, "uid": user_id},
    )
    return res.first() is not None


class DuplicatePortalEmailError(Exception):
    """Email already registered."""


async def safe_insert_portal_user(
    session: AsyncSession,
    email: str,
    password_hash: str,
) -> UUID:
    try:
        return await insert_portal_user(session, email, password_hash)
    except IntegrityError as e:
        orig = getattr(e, "orig", None)
        if getattr(orig, "pgcode", None) == "23505":
            raise DuplicatePortalEmailError from e
        raise
