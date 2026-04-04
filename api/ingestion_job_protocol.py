"""Ingestion job store protocol (Postgres default; in-memory for unit tests)."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class IngestionJobRepository(Protocol):
    """Persist ingestion job lifecycle. Swap implementation in tests via FastAPI overrides."""

    async def create_job(self, *, user_id: UUID, source: str) -> str:
        """Insert ``queued`` row; return job id string."""

    async def get_job_for_user(self, *, job_id: str, user_id: UUID) -> dict[str, Any] | None:
        """Return job row dict or ``None`` if missing / not owned by user."""

    async def mark_running(self, *, job_id: str) -> None:
        """Transition ``queued`` → ``running`` (no-op if row missing)."""

    async def mark_failed(
        self,
        *,
        job_id: str,
        message: str,
        docs_indexed: int = 0,
    ) -> None:
        """Set ``failed`` + error message."""

    async def mark_succeeded(self, *, job_id: str, docs_indexed: int) -> None:
        """Set ``complete``."""
