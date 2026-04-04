"""In-memory ingestion job store for fast API unit tests."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from uuid import UUID


class InMemoryIngestionJobRepository:
    """Test double for :class:`IngestionJobRepository`."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, *, user_id: UUID, source: str) -> str:
        jid = str(uuid.uuid4())
        async with self._lock:
            self._jobs[jid] = {
                "user_id": user_id,
                "source": source,
                "status": "queued",
                "docs_indexed": 0,
                "error": None,
            }
        return jid

    async def get_job_for_user(self, *, job_id: str, user_id: UUID) -> dict[str, Any] | None:
        async with self._lock:
            row = self._jobs.get(job_id)
        if row is None or row["user_id"] != user_id:
            return None
        return {
            "status": row["status"],
            "docs_indexed": int(row["docs_indexed"] or 0),
            "error": row["error"],
        }

    async def mark_running(self, *, job_id: str) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "running"

    async def mark_failed(
        self,
        *,
        job_id: str,
        message: str,
        docs_indexed: int = 0,
    ) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(
                    status="failed",
                    error=message,
                    docs_indexed=docs_indexed,
                )

    async def mark_succeeded(self, *, job_id: str, docs_indexed: int) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(
                    status="complete",
                    docs_indexed=docs_indexed,
                    error=None,
                )
