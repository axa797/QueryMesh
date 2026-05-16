"""Schemas for persisted RAGAS eval reports (``GET /eval-reports``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvalReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    mode: str
    n_samples: int
    aggregate_metrics: dict[str, float]
    judge_model: str
    embedding_model: str
    langfuse_trace_id: str | None = Field(
        default=None,
        description=(
            "Langfuse UI URL from ragas_eval get_trace_url where possible; else bare trace id."
        ),
    )
    trigger: str


class EvalReportDetail(EvalReportSummary):
    per_row_metrics: list[dict[str, Any]]
    git_commit: str | None = None


class PaginatedEvalReports(BaseModel):
    items: list[EvalReportSummary]
    total: int
    page: int
    page_size: int
