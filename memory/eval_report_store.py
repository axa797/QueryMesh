"""RAGAS / eval summaries persisted from ``evals.ragas_eval``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from memory.session import session_scope


def _coerce_agg(obj: Any) -> dict[str, float]:
    raw: Any = obj
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            out[str(k)] = float(v)
    return out


async def insert_eval_report(
    *,
    mode: str,
    n_samples: int,
    aggregate_metrics: dict[str, Any],
    per_row_metrics: list[dict[str, Any]] | None,
    judge_model: str,
    embedding_model: str,
    langfuse_trace_id: str | None,
    trigger: str = "manual",
    git_commit: str | None = None,
) -> UUID:
    per_bind: str | None
    if per_row_metrics is None:
        per_bind = None
    else:
        per_bind = json.dumps(per_row_metrics)

    async with session_scope() as session:
        res = await session.execute(
            text(
                """
                INSERT INTO eval_reports (
                  mode, n_samples,
                  aggregate_metrics, per_row_metrics,
                  judge_model, embedding_model,
                  langfuse_trace_id, trigger_source, git_commit
                )
                VALUES (
                  :mode, :n_samples,
                  CAST(:aggregate AS jsonb),
                  CAST(:per_row AS jsonb),
                  :judge, :emb,
                  :lf_trace, :trigger_src, :git_commit
                )
                RETURNING id
                """
            ),
            {
                "mode": mode,
                "n_samples": int(n_samples),
                "aggregate": json.dumps(aggregate_metrics),
                "per_row": per_bind,
                "judge": judge_model[:512],
                "emb": embedding_model[:256],
                "lf_trace": (langfuse_trace_id or "")[:512] or None,
                "trigger_src": trigger[:64],
                "git_commit": (git_commit or "")[:64] or None,
            },
        )
        rid = res.scalar_one()
        return UUID(str(rid))


async def list_eval_reports_page(
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    async with session_scope() as session:
        cr = await session.execute(text("SELECT COUNT(*) FROM eval_reports"))
        total = int(cr.scalar_one() or 0)
        qr = await session.execute(
            text(
                """
                SELECT id::text AS id,
                       created_at,
                       mode,
                       n_samples,
                       aggregate_metrics,
                       judge_model,
                       embedding_model,
                       langfuse_trace_id,
                       trigger_source
                FROM eval_reports
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {"lim": limit, "off": offset},
        )
        rows = qr.mappings().all()

    items: list[dict[str, Any]] = []
    for row in rows:
        created = row["created_at"]
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created_at = created.replace(tzinfo=UTC)
            else:
                created_at = created
        else:
            created_at = datetime.now(UTC)
        agg = _coerce_agg(row.get("aggregate_metrics"))
        items.append(
            {
                "id": row["id"],
                "created_at": created_at,
                "mode": row["mode"],
                "n_samples": int(row["n_samples"]),
                "aggregate_metrics": agg,
                "judge_model": row["judge_model"],
                "embedding_model": row["embedding_model"],
                "langfuse_trace_id": row.get("langfuse_trace_id"),
                "trigger": row["trigger_source"],
            },
        )
    return items, total


async def fetch_eval_report_by_id(report_id: str) -> dict[str, Any] | None:
    try:
        rid = UUID(report_id)
    except ValueError:
        return None

    async with session_scope() as session:
        res = await session.execute(
            text(
                """
                SELECT id::text AS id,
                       created_at,
                       mode,
                       n_samples,
                       aggregate_metrics,
                       per_row_metrics,
                       judge_model,
                       embedding_model,
                       langfuse_trace_id,
                       trigger_source,
                       git_commit
                FROM eval_reports WHERE id = :id
                """
            ),
            {"id": str(rid)},
        )
        row = res.mappings().first()
    if row is None:
        return None

    def _loads_per(obj: Any) -> list[Any]:
        if obj is None:
            return []
        if isinstance(obj, list):
            return obj
        if isinstance(obj, str):
            try:
                v = json.loads(obj)
                return v if isinstance(v, list) else []
            except json.JSONDecodeError:
                return []
        return []

    created = row["created_at"]
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created_at = created.replace(tzinfo=UTC)
        else:
            created_at = created
    else:
        created_at = datetime.now(UTC)

    agg_raw = row.get("aggregate_metrics")
    agg = _coerce_agg(agg_raw)

    per = _loads_per(row.get("per_row_metrics"))

    return {
        "id": row["id"],
        "created_at": created_at,
        "mode": row["mode"],
        "n_samples": int(row["n_samples"]),
        "aggregate_metrics": agg,
        "per_row_metrics": per,
        "judge_model": row["judge_model"],
        "embedding_model": row["embedding_model"],
        "langfuse_trace_id": row.get("langfuse_trace_id"),
        "trigger": row["trigger_source"],
        "git_commit": row.get("git_commit"),
    }
