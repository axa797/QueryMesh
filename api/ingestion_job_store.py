"""Postgres-backed ingestion job store."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from memory.session import session_scope
from sqlalchemy import text


class PostgresIngestionJobRepository:
    """Job state in the ``ingestion_jobs`` Postgres table."""

    async def create_job(self, *, user_id: UUID, source: str) -> str:
        jid = uuid.uuid4()
        async with session_scope() as session:
            await session.execute(
                text(
                    "INSERT INTO ingestion_jobs (id, user_id, source, status, docs_indexed) "
                    "VALUES (:id, :user_id, :source, 'queued', 0)"
                ),
                {"id": str(jid), "user_id": str(user_id), "source": source},
            )
        return str(jid)

    async def get_job_for_user(self, *, job_id: str, user_id: UUID) -> dict[str, Any] | None:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return None
        async with session_scope() as session:
            result = await session.execute(
                text(
                    "SELECT status, docs_indexed, error FROM ingestion_jobs "
                    "WHERE id = :id AND user_id = :user_id"
                ),
                {"id": str(jid), "user_id": str(user_id)},
            )
            row = result.mappings().first()
        if row is None:
            return None
        return {
            "status": row["status"],
            "docs_indexed": int(row["docs_indexed"] or 0),
            "error": row["error"],
        }

    async def mark_running(self, *, job_id: str) -> None:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE ingestion_jobs SET status = 'running', updated_at = NOW() "
                    "WHERE id = :id"
                ),
                {"id": str(jid)},
            )

    async def mark_failed(
        self,
        *,
        job_id: str,
        message: str,
        docs_indexed: int = 0,
    ) -> None:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE ingestion_jobs SET status = 'failed', error = :error, "
                    "docs_indexed = :docs_indexed, updated_at = NOW() WHERE id = :id"
                ),
                {"id": str(jid), "error": message, "docs_indexed": docs_indexed},
            )

    async def mark_succeeded(self, *, job_id: str, docs_indexed: int) -> None:
        try:
            jid = uuid.UUID(job_id)
        except ValueError:
            return
        async with session_scope() as session:
            await session.execute(
                text(
                    "UPDATE ingestion_jobs SET status = 'complete', docs_indexed = :n, "
                    "error = NULL, updated_at = NOW() WHERE id = :id"
                ),
                {"id": str(jid), "n": docs_indexed},
            )
