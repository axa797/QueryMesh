"""List and fetch persisted RAGAS eval reports."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from memory.eval_report_store import fetch_eval_report_by_id, list_eval_reports_page

from api.deps import CurrentUserId
from api.schemas.eval_report import EvalReportDetail, EvalReportSummary, PaginatedEvalReports

router = APIRouter(prefix="/eval-reports")


@router.get("")
async def list_eval_reports_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user_id: CurrentUserId = ...,
) -> PaginatedEvalReports:
    offset = (page - 1) * page_size
    rows, total = await list_eval_reports_page(limit=page_size, offset=offset)
    items = [EvalReportSummary.model_validate(r) for r in rows]
    return PaginatedEvalReports(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{report_id}")
async def get_eval_report_endpoint(
    report_id: str,
    _user_id: CurrentUserId = ...,
) -> EvalReportDetail:
    row = await fetch_eval_report_by_id(report_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": "Unknown eval report id.",
            },
        )
    return EvalReportDetail.model_validate(row)
