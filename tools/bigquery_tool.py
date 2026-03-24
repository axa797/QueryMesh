"""BigQuery read-only execution for the analytics agent (spec §6.4)."""

from __future__ import annotations

import re
from typing import Any

from google.cloud import bigquery

# Frozen schema text for LLM prompts (must match scripts/bootstrap_bq.py).
DOC_METADATA_TABLE = "doc_metadata"
_SCHEMA_LINES = (
    "Table `{project}.{dataset}.doc_metadata` columns:\n"
    "- doc_name STRING (PDF filename)\n"
    "- section STRING\n"
    "- word_count INT64\n"
    "- last_updated DATE\n"
    "- product_area STRING (e.g. Cloud Run, BigQuery, GKE)\n"
)

_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|MERGE|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE,
)
_MAX_ROWS = 500


def schema_prompt_fragment(*, project: str, dataset: str) -> str:
    return _SCHEMA_LINES.format(project=project, dataset=dataset)


def validate_read_only_sql(sql: str) -> str:
    """Allow a single SELECT or WITH … SELECT; reject mutating statements."""
    s = (sql or "").strip()
    if not s:
        raise ValueError("SQL is empty")
    chunks = [c.strip() for c in s.split(";") if c.strip()]
    if len(chunks) != 1:
        raise ValueError("exactly one SQL statement is required")
    stmt = chunks[0]
    if _FORBIDDEN.search(stmt):
        raise ValueError("mutating or DDL keywords are not allowed")
    head = stmt.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        raise ValueError("only SELECT (or WITH … SELECT) queries are allowed")
    return stmt


def run_query(
    sql: str,
    *,
    project_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """Run validated read-only SQL; returns rows as dicts (capped) and reported row count."""
    safe = validate_read_only_sql(sql)
    client = bigquery.Client(project=project_id)
    job = client.query(
        safe,
        job_config=bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=500_000_000,
        ),
    )
    iterator = job.result(max_results=_MAX_ROWS + 1)
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(iterator):
        if i >= _MAX_ROWS:
            break
        rows.append({k: _serialize_value(row[k]) for k in row.keys()})

    total = iterator.total_rows
    if total is not None:
        n = int(total)
    else:
        n = len(rows)
    return rows, n


def _serialize_value(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return v
