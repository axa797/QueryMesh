#!/usr/bin/env python3
"""Create a user row (if needed) and an API key. Prints the raw key once (keep it secret)."""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid

from api.auth import digest_api_key
from api.settings import get_settings
from memory.session import session_scope
from sqlalchemy import text


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mint API key for querymesh.")
    p.add_argument(
        "--user-id",
        type=uuid.UUID,
        default=None,
        help="Existing users.id (default: insert new user)",
    )
    return p.parse_args()


async def _run(user_id: uuid.UUID | None) -> None:
    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    digest = digest_api_key(raw, settings.api_key_pepper)

    async with session_scope() as session:
        uid = user_id
        if uid is None:
            res = await session.execute(text("INSERT INTO users DEFAULT VALUES RETURNING id"))
            uid = res.scalar_one()
        await session.execute(
            text("INSERT INTO api_keys (user_id, key_digest) VALUES (:uid, :digest)"),
            {"uid": uid, "digest": digest},
        )

    print(f"user_id={uid}", file=sys.stderr)
    print(raw)


def main() -> int:
    args = _parse_args()
    asyncio.run(_run(args.user_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
