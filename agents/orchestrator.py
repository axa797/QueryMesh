"""Routing orchestrator (spec §6.1): temp=0, JSON route, retry once, RAG fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Self

from api.settings import get_settings
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.jsonutil import strip_markdown_fences
from agents.vertex import vertex_client

log = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM = (
    "You are a routing orchestrator. Given a user query, classify it into one "
    "or more of the following intents: [retrieval, code_generation, analytics].\n\n"
    "Return a JSON object:\n"
    "{\n"
    '  "intents": ["retrieval"],\n'
    '  "rewritten_queries": {\n'
    '    "retrieval": "..."\n'
    "  },\n"
    '  "parallel": true\n'
    "}\n\n"
    "Rules:\n"
    "- intents: one or more of retrieval, code_generation, analytics "
    "(at most 3 distinct).\n"
    "- rewritten_queries: include one optimized string per intent key you return.\n"
    "- parallel: true if specialists can run concurrently, else false.\n"
    "- Ambiguous or general knowledge questions default to retrieval only."
)

REPAIR_USER_TEMPLATE = (
    "Your previous answer was not usable. Return ONLY a JSON object with keys "
    "intents (array of strings), rewritten_queries (object string->string), "
    "parallel (boolean). No markdown.\n\n"
    "Invalid or incomplete output:\n"
    "{invalid}\n\n"
    "Fix it for the original user query:\n"
    "{query}\n"
)


class OrchestratorJSON(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intents: list[str]
    rewritten_queries: dict[str, str] = Field(default_factory=dict)
    parallel: bool = False

    @field_validator("intents", mode="before")
    @classmethod
    def _clean_intents(cls, v: object) -> list[str]:
        allowed = frozenset({"retrieval", "code_generation", "analytics"})
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("intents must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            s = str(item).strip()
            if s in allowed and s not in seen:
                out.append(s)
                seen.add(s)
            if len(out) >= 3:
                break
        return out

    @model_validator(mode="after")
    def _non_empty_intents(self) -> Self:
        if not self.intents:
            raise ValueError("intents must be non-empty")
        return self


def _normalize_payload(data: dict[str, Any], original_query: str, *, source: str) -> dict[str, Any]:
    parsed = OrchestratorJSON.model_validate(data)
    intents = list(parsed.intents)
    q = (original_query or "").strip()
    rq: dict[str, str] = {}
    for intent in intents:
        raw_rq = parsed.rewritten_queries.get(intent)
        rtext = (raw_rq or "").strip() if isinstance(raw_rq, str) else ""
        rq[intent] = rtext if rtext else q
    return {
        "intents": intents,
        "rewritten_queries": rq,
        "parallel": bool(parsed.parallel),
        "source": source,
    }


def rag_fallback_route(query: str, *, source: str) -> dict[str, Any]:
    q = (query or "").strip()
    return {
        "intents": ["retrieval"],
        "rewritten_queries": {"retrieval": q},
        "parallel": False,
        "source": source,
    }


def parse_route_json(text: str, original_query: str, *, source: str) -> dict[str, Any]:
    cleaned = strip_markdown_fences(text)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")
    return _normalize_payload(data, original_query, source=source)


def _generate_route_text(
    *,
    user_message: str,
    repair_message: str | None,
    model_id: str,
    project: str,
    location: str,
) -> str:
    client = vertex_client(project, location)
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=ORCHESTRATOR_SYSTEM,
        response_mime_type="application/json",
    )
    parts: list[str] = [user_message]
    if repair_message is not None:
        parts.append(repair_message)
    payload = "\n\n".join(parts)
    resp = client.models.generate_content(model=model_id, contents=payload, config=cfg)
    t = getattr(resp, "text", None)
    if not t and resp.candidates:
        parts_out = []
        for c in resp.candidates:
            if not c.content or not c.content.parts:
                continue
            for p in c.content.parts:
                if getattr(p, "text", None):
                    parts_out.append(p.text)
        t = "\n".join(parts_out) if parts_out else None
    if not t:
        raise RuntimeError("empty orchestrator model response")
    return t


def _user_block(query: str, memory_compact: str) -> str:
    q = (query or "").strip()
    mem = (memory_compact or "").strip()
    if mem:
        return (
            "User query:\n"
            f"{q}\n\n"
            "Optional long-term memory summary (routing context only; do not echo verbatim):\n"
            f"{mem[:4000]}"
        )
    return f"User query:\n{q}"


async def run_orchestrator(query: str, memory_compact: str) -> dict[str, Any]:
    """Call Vertex Gemini once plus optional repair; on failure return RAG-only route."""
    settings = get_settings()
    project = settings.google_cloud_project
    if not project:
        log.info("Orchestrator: no google_cloud_project; RAG-only fallback")
        return rag_fallback_route(query, source="fallback_no_gcp")

    user_first = _user_block(query, memory_compact)
    model_id = settings.vertex_llm_model
    location = settings.google_cloud_location
    text = ""

    try:
        text = await asyncio.to_thread(
            _generate_route_text,
            user_message=user_first,
            repair_message=None,
            model_id=model_id,
            project=project,
            location=location,
        )
        return parse_route_json(text, query, source="llm")
    except Exception as e:
        if log.isEnabledFor(logging.DEBUG):
            log.warning("Orchestrator first pass failed: %s", e, exc_info=True)
        else:
            log.warning("Orchestrator first pass failed: %s", e)

    invalid_snip = (text or "")[:2000]
    qstrip = (query or "").strip()
    repair = REPAIR_USER_TEMPLATE.format(
        invalid=invalid_snip or "(no text)",
        query=qstrip,
    )
    try:
        text2 = await asyncio.to_thread(
            _generate_route_text,
            user_message=user_first,
            repair_message=repair,
            model_id=model_id,
            project=project,
            location=location,
        )
        return parse_route_json(text2, query, source="llm_retry")
    except Exception:
        log.exception("Orchestrator retry failed; defaulting to RAG-only")

    return rag_fallback_route(query, source="fallback_parse")
