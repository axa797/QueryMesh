"""In-process ingestion job tracker (Phase 15 local; prod: persist + Cloud Run Job)."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Literal

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

JobStatus = Literal["running", "complete", "failed"]


def job_create() -> str:
    jid = str(uuid.uuid4())
    with _lock:
        _jobs[jid] = {
            "status": "running",
            "docs_indexed": 0,
            "error": None,
        }
    return jid


def job_fail(job_id: str, message: str, docs_indexed: int = 0) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id] = {
            "status": "failed",
            "docs_indexed": docs_indexed,
            "error": message,
        }


def job_succeed(job_id: str, docs_indexed: int) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id] = {
            "status": "complete",
            "docs_indexed": docs_indexed,
            "error": None,
        }


def job_view(job_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _jobs.get(job_id)
        if row is None:
            return None
        return dict(row)


def reset_jobs_for_tests() -> None:
    with _lock:
        _jobs.clear()
