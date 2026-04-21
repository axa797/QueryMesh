"""Request/response models for portal signup and API key management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


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
