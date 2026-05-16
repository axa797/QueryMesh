"""Redis session envelope: mint, bind, and validate session_id (spec §7–§8)."""

from __future__ import annotations

import json
import uuid
from uuid import UUID

import redis.asyncio as redis
from fastapi import HTTPException

from memory.checkpointer import checkpoint_exists_for_thread

SESSION_KEY_PREFIX = "querymesh:session:"
SESSION_TTL_SEC = 24 * 60 * 60


def envelope_key(session_id: UUID) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def thread_id_for(user_internal_id: UUID, session_id: UUID) -> str:
    return f"{user_internal_id}:{session_id}"


def invalid_session_detail() -> dict[str, str]:
    return {
        "error": "invalid_session",
        "message": "Session is unknown or does not belong to this API key.",
    }


async def resolve_session(
    redis_client: redis.Redis,
    user_internal_id: UUID,
    session_id_raw: str | None,
) -> tuple[UUID, str]:
    """Return (session_id, thread_id) for LangGraph; persist or validate Redis envelope."""
    if session_id_raw is None or not session_id_raw.strip():
        sid = uuid.uuid4()
        tid = thread_id_for(user_internal_id, sid)
        payload = {
            "user_id": str(user_internal_id),
            "session_id": str(sid),
            "thread_id": tid,
        }
        await redis_client.setex(
            envelope_key(sid),
            SESSION_TTL_SEC,
            json.dumps(payload),
        )
        return sid, tid

    try:
        sid = uuid.UUID(session_id_raw.strip())
    except ValueError:
        raise HTTPException(status_code=403, detail=invalid_session_detail()) from None

    raw = await redis_client.get(envelope_key(sid))
    if raw is None:
        # Redis TTL expired or eviction; rebind if Postgres still has graph state.
        expected_tid = thread_id_for(user_internal_id, sid)
        try:
            has_cp = await checkpoint_exists_for_thread(expected_tid)
        except Exception:
            has_cp = False
        if has_cp:
            payload = {
                "user_id": str(user_internal_id),
                "session_id": str(sid),
                "thread_id": expected_tid,
            }
            await redis_client.setex(
                envelope_key(sid),
                SESSION_TTL_SEC,
                json.dumps(payload),
            )
            return sid, expected_tid
        raise HTTPException(status_code=403, detail=invalid_session_detail())

    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=403, detail=invalid_session_detail()) from None

    uid_s = env.get("user_id")
    if uid_s != str(user_internal_id):
        raise HTTPException(status_code=403, detail=invalid_session_detail())

    tid = env.get("thread_id") or ""
    expected_tid = thread_id_for(user_internal_id, sid)
    if tid != expected_tid:
        raise HTTPException(status_code=403, detail=invalid_session_detail())

    return sid, expected_tid
