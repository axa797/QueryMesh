"""Where ingestion work is scheduled (BackgroundTasks today; Cloud Run Job later).

Phase 2: ``FastAPI.BackgroundTasks`` runs ``run_ingestion_job`` in-process.

Future: replace ``schedule_ingestion_job`` to enqueue ``(job_id, source)`` for a Cloud Run Job
or external worker; keep ``run_ingestion_job`` as the worker entrypoint.
"""

from __future__ import annotations

from fastapi import BackgroundTasks


def schedule_ingestion_job(
    background_tasks: BackgroundTasks,
    job_id: str,
    source: str,
) -> None:
    """Register ingestion work. Hook: swap this function for non-in-process runners."""
    from api.ingestion_runner import run_ingestion_job

    background_tasks.add_task(run_ingestion_job, job_id, source)
