"""Analytics agent: NL → guarded BigQuery SELECT → structured JSON (spec §6.4)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from api.settings import get_settings
from google.genai import types
from pydantic import BaseModel, Field
from tools.bigquery_tool import run_query, schema_prompt_fragment, validate_read_only_sql

from agents.jsonutil import strip_markdown_fences
from agents.vertex import vertex_client

log = logging.getLogger(__name__)

SQL_MODEL_SYSTEM = (
    "You are a BigQuery SQL expert. From the user's question, output ONE read-only "
    "Standard SQL query against the described table only.\n"
    "Use fully qualified table names as given. Prefer explicit column lists or SELECT * "
    "for this small schema.\n"
    "Return JSON with a single key: sql (string). No markdown."
)


class SqlJson(BaseModel):
    sql: str = Field(min_length=1)


def _response_text(resp: Any) -> str:
    t = getattr(resp, "text", None)
    if t:
        return t
    if resp.candidates:
        parts_out = []
        for c in resp.candidates:
            if not c.content or not c.content.parts:
                continue
            for p in c.content.parts:
                if getattr(p, "text", None):
                    parts_out.append(p.text)
        if parts_out:
            return "\n".join(parts_out)
    return ""


def _bq_project_and_dataset(settings: Any) -> tuple[str | None, str]:
    proj = settings.bigquery_project_id or settings.google_cloud_project
    return proj, settings.bigquery_dataset


def _generate_sql_sync(*, user_blob: str, model_id: str, project: str, location: str) -> str:
    client = vertex_client(project, location)
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=SQL_MODEL_SYSTEM,
        response_mime_type="application/json",
    )
    resp = client.models.generate_content(model=model_id, contents=user_blob, config=cfg)
    text = _response_text(resp)
    if not text:
        raise RuntimeError("empty analytics SQL response")
    return text


async def run_analytics(question: str) -> dict[str, Any]:
    """Generate SQL with Gemini, validate, execute on BigQuery (ADC)."""
    settings = get_settings()
    bq_proj, dataset = _bq_project_and_dataset(settings)
    if not bq_proj:
        return {
            "sql": None,
            "results": [],
            "row_count": 0,
            "interpretation": (
                "BigQuery is not configured (set BIGQUERY_PROJECT_ID or GOOGLE_CLOUD_PROJECT)."
            ),
            "source": "fallback_no_bq",
        }

    vertex_proj = settings.google_cloud_project
    if not vertex_proj:
        return {
            "sql": None,
            "results": [],
            "row_count": 0,
            "interpretation": "Vertex (GOOGLE_CLOUD_PROJECT) is required to generate SQL.",
            "source": "fallback_no_vertex",
        }

    schema = schema_prompt_fragment(project=bq_proj, dataset=dataset)
    fq = f"`{bq_proj}.{dataset}.doc_metadata`"
    user_blob = (
        f"{schema}\nUse this table id in your query: {fq}\n\nUser question:\n{question.strip()}\n"
    )

    try:
        raw = await asyncio.to_thread(
            _generate_sql_sync,
            user_blob=user_blob,
            model_id=settings.vertex_llm_model,
            project=vertex_proj,
            location=settings.google_cloud_location,
        )
        data = json.loads(strip_markdown_fences(raw))
        sql = SqlJson.model_validate(data).sql.strip()
        validate_read_only_sql(sql)
    except Exception as e:
        if log.isEnabledFor(logging.DEBUG):
            log.warning(
                "Analytics SQL generation/validation failed: %s",
                e,
                exc_info=True,
            )
        else:
            log.warning("Analytics SQL generation/validation failed: %s", e)
        return {
            "sql": None,
            "results": [],
            "row_count": 0,
            "interpretation": f"Could not produce valid analytics SQL: {e}",
            "source": "fallback_parse",
        }

    try:
        results, row_count = await asyncio.to_thread(
            run_query,
            sql,
            project_id=bq_proj,
            job_location=None,
        )
    except Exception as e:
        log.exception("BigQuery query failed")
        return {
            "sql": sql,
            "results": [],
            "row_count": 0,
            "interpretation": f"BigQuery execution failed: {e}",
            "source": "bq_error",
        }

    return {
        "sql": sql,
        "results": results,
        "row_count": row_count,
        "interpretation": f"Returned {row_count} row(s) from doc metadata (results may be capped).",
        "source": "llm",
    }
