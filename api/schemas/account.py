"""Response models for portal JWT (fragment callback) and API key APIs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PortalTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID


class ApiKeyCreateResponse(BaseModel):
    api_key: str
    key_id: UUID


class ApiKeyListItem(BaseModel):
    key_id: UUID
    created_at: datetime
    revoked_at: datetime | None
