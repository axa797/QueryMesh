"""Request/response models for ``POST /ingest`` (spec §8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source: Literal["gcp_docs"] = Field(description="Document corpus key")


class IngestStartResponse(BaseModel):
    status: Literal["started"] = "started"
    job_id: str


class IngestStatusResponse(BaseModel):
    status: Literal["running", "complete", "failed"]
    docs_indexed: int
    error: str | None = None
