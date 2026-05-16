"""Postgres helpers: portal users and API keys (same tables as mint script)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_user_from_google(
    session: AsyncSession,
    *,
    email: str,
    google_sub: str,
) -> UUID:
    """Create or attach a portal user from verified Google OAuth claims.

    - Match by google_sub → return existing id.
    - Else match by lower(email) → set google_sub and clear password_hash.
    - Else INSERT with password_hash NULL.
    """
    email_l = email.strip().lower()

    row = (
        await session.execute(
            text("SELECT id::text FROM users WHERE google_sub = :gs"),
            {"gs": google_sub},
        )
    ).mappings().first()
    if row is not None:
        return UUID(str(row["id"]))

    row2 = (
        await session.execute(
            text(
                """
                SELECT id::text FROM users
                WHERE email IS NOT NULL AND lower(trim(email)) = :em
                """
            ),
            {"em": email_l},
        )
    ).mappings().first()
    if row2 is not None:
        uid = UUID(str(row2["id"]))
        await session.execute(
            text(
                """
                UPDATE users
                SET google_sub = :gs, password_hash = NULL
                WHERE id = CAST(:uid AS uuid)
                """
            ),
            {"gs": google_sub, "uid": str(uid)},
        )
        return uid

    res = await session.execute(
        text(
            """
            INSERT INTO users (email, google_sub, password_hash)
            VALUES (:em, :gs, NULL)
            RETURNING id::text
            """
        ),
        {"em": email_l, "gs": google_sub},
    )
    return UUID(str(res.scalar_one()))


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
