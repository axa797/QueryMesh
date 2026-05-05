"""Background ingestion worker (calls ``ingestion.indexer.run_index``)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ingestion.indexer import RunIndexResult, run_index

from api.deps import get_ingestion_job_repository
from api.settings import get_settings

log = logging.getLogger(__name__)


async def run_ingestion_job(job_id: str, source: str) -> None:
    """Async entrypoint for FastAPI ``BackgroundTasks`` (or a future Cloud Run Job worker)."""
    repo = get_ingestion_job_repository()
    await repo.mark_running(job_id=job_id)

    if source != "gcp_docs":
        await repo.mark_failed(job_id=job_id, message=f"Unsupported source: {source}")
        return

    settings = get_settings()
    raw = (settings.ingestion_gcp_docs_dir or "").strip()
    if not raw:
        await repo.mark_failed(
            job_id=job_id,
            message="INGESTION_GCP_DOCS_DIR is not set (directory of documents to index).",
        )
        return

    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        await repo.mark_failed(
            job_id=job_id,
            message=f"Ingestion source is not a directory: {root}",
        )
        return

    project = settings.google_cloud_project
    if not project:
        await repo.mark_failed(
            job_id=job_id,
            message="GOOGLE_CLOUD_PROJECT is required to embed chunks with Vertex.",
        )
        return

    log.info("Starting ingestion job %s from %s", job_id, root)

    def _run_sync() -> RunIndexResult:
        return run_index(
            source=root,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key,
            collection=settings.qdrant_collection,
            project=project,
            location=settings.google_cloud_location,
            model_id=settings.vertex_embedding_model,
            recreate=settings.ingestion_recreate_collection,
            qdrant_timeout_seconds=settings.qdrant_timeout_seconds,
        )

    try:
        result = await asyncio.to_thread(_run_sync)
    except Exception as exc:  # pragma: no cover — defensive; run_index should return result
        log.exception("Ingestion job %s crashed", job_id)
        await repo.mark_failed(job_id=job_id, message=str(exc))
        return

    if result.exit_code != 0:
        await repo.mark_failed(
            job_id=job_id,
            message=result.message or "Ingestion failed",
            docs_indexed=result.docs_indexed,
        )
        log.warning("Ingestion job %s failed: %s", job_id, result.message)
        return

    await repo.mark_succeeded(job_id=job_id, docs_indexed=result.docs_indexed)
    log.info("Ingestion job %s complete (%s points)", job_id, result.docs_indexed)
