"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from memory.session import get_session_factory

from api.auth import lookup_user_for_api_key
from api.ingestion_job_protocol import IngestionJobRepository
from api.ingestion_job_store import PostgresIngestionJobRepository
from api.portal_jwt import decode_portal_sub
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


async def get_portal_user_id(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
) -> UUID:
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
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_session",
                "message": "Missing or invalid Authorization (portal Bearer JWT).",
            },
        )
    try:
        return decode_portal_sub(token=creds.credentials.strip(), secret=secret)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_session",
                "message": "Invalid or expired portal session.",
            },
        ) from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_session",
                "message": "Invalid or expired portal session.",
            },
        ) from None


CurrentUserId = Annotated[UUID, Depends(get_current_user_internal_id)]
PortalUserId = Annotated[UUID, Depends(get_portal_user_id)]

_postgres_ingestion_repo = PostgresIngestionJobRepository()
_ingestion_repo_override: IngestionJobRepository | None = None


def get_ingestion_job_repository() -> IngestionJobRepository:
    if _ingestion_repo_override is not None:
        return _ingestion_repo_override
    return _postgres_ingestion_repo


def set_ingestion_job_repository_for_tests(repo: IngestionJobRepository | None) -> None:
    """Point ingestion at an in-memory store in unit tests."""
    global _ingestion_repo_override
    _ingestion_repo_override = repo


IngestionJobRepo = Annotated[IngestionJobRepository, Depends(get_ingestion_job_repository)]
