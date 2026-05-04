"""POST /ingest + GET /ingest/{job_id}."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.deps import CurrentUserId, IngestionJobRepo
from api.ingestion_schedule import schedule_ingestion_job
from api.schemas.ingest import IngestRequest, IngestStartResponse, IngestStatusResponse

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestStartResponse)
async def post_ingest(
    user_id: CurrentUserId,
    body: IngestRequest,
    background_tasks: BackgroundTasks,
    repo: IngestionJobRepo,
) -> IngestStartResponse:
    """Start embedding/indexing in the background (in-process ``BackgroundTasks``)."""
    job_id = await repo.create_job(user_id=user_id, source=body.source)
    schedule_ingestion_job(background_tasks, job_id, body.source)
    return IngestStartResponse(job_id=job_id)


@router.get("/ingest/{job_id}", response_model=IngestStatusResponse)
async def get_ingest_status(
    job_id: str,
    user_id: CurrentUserId,
    repo: IngestionJobRepo,
) -> IngestStatusResponse:
    row = await repo.get_job_for_user(job_id=job_id, user_id=user_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_job",
                "message": "No ingestion job exists with this id.",
            },
        )
    st = row["status"]
    if st not in ("queued", "running", "complete", "failed"):
        st = "failed"
    return IngestStatusResponse(
        status=st,
        docs_indexed=int(row.get("docs_indexed") or 0),
        error=row.get("error"),
    )
