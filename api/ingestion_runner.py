"""Background ingestion worker (calls ``ingestion.indexer.run_index``)."""

from __future__ import annotations

import logging
from pathlib import Path

from ingestion.indexer import run_index

from api import ingestion_jobs
from api.settings import get_settings

log = logging.getLogger(__name__)


def run_ingestion_job(job_id: str, source: str) -> None:
    """Sync entrypoint for FastAPI ``BackgroundTasks``."""
    if source != "gcp_docs":
        ingestion_jobs.job_fail(job_id, f"Unsupported source: {source}")
        return

    settings = get_settings()
    raw = (settings.ingestion_gcp_docs_dir or "").strip()
    if not raw:
        ingestion_jobs.job_fail(
            job_id,
            "INGESTION_GCP_DOCS_DIR is not set (directory of documents to index).",
        )
        return

    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        ingestion_jobs.job_fail(job_id, f"Ingestion source is not a directory: {root}")
        return

    project = settings.google_cloud_project
    if not project:
        ingestion_jobs.job_fail(
            job_id,
            "GOOGLE_CLOUD_PROJECT is required to embed chunks with Vertex.",
        )
        return

    log.info("Starting ingestion job %s from %s", job_id, root)
    result = run_index(
        source=root,
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key,
        collection=settings.qdrant_collection,
        project=project,
        location=settings.google_cloud_location,
        model_id=settings.vertex_embedding_model,
        recreate=settings.ingestion_recreate_collection,
    )
    if result.exit_code != 0:
        ingestion_jobs.job_fail(
            job_id,
            result.message or "Ingestion failed",
            docs_indexed=result.docs_indexed,
        )
        log.warning("Ingestion job %s failed: %s", job_id, result.message)
        return

    ingestion_jobs.job_succeed(job_id, result.docs_indexed)
    log.info("Ingestion job %s complete (%s points)", job_id, result.docs_indexed)
