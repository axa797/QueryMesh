"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from memory.session import get_session_factory

from api.auth import lookup_user_for_api_key
from api.settings import get_settings

http_bearer = HTTPBearer(auto_error=False)


async def get_current_user_internal_id(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
) -> UUID:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_api_key",
                "message": "Missing or invalid Authorization header (expected Bearer token).",
            },
        )
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        user_id = await lookup_user_for_api_key(
            session,
            creds.credentials.strip(),
            settings.api_key_pepper,
        )
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_api_key",
                "message": "Unknown or revoked API key.",
            },
        )
    return user_id


CurrentUserId = Annotated[UUID, Depends(get_current_user_internal_id)]
