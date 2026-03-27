"""POST /ingest + GET /ingest/{job_id} (spec §8, Phase 15)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api import ingestion_jobs
from api.deps import CurrentUserId
from api.ingestion_runner import run_ingestion_job
from api.schemas.ingest import IngestRequest, IngestStartResponse, IngestStatusResponse

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestStartResponse)
async def post_ingest(
    _user_id: CurrentUserId,
    body: IngestRequest,
    background_tasks: BackgroundTasks,
) -> IngestStartResponse:
    """Start embedding/indexing in the background (local: ``BackgroundTasks``)."""
    job_id = ingestion_jobs.job_create()
    background_tasks.add_task(run_ingestion_job, job_id, body.source)
    return IngestStartResponse(job_id=job_id)


@router.get("/ingest/{job_id}", response_model=IngestStatusResponse)
async def get_ingest_status(
    job_id: str,
    _user_id: CurrentUserId,
) -> IngestStatusResponse:
    row = ingestion_jobs.job_view(job_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_job",
                "message": "No ingestion job exists with this id.",
            },
        )
    st = row["status"]
    if st not in ("running", "complete", "failed"):
        st = "failed"
    return IngestStatusResponse(
        status=st,
        docs_indexed=int(row.get("docs_indexed") or 0),
        error=row.get("error"),
    )
