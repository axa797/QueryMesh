"""RAG specialist: retrieval context → structured JSON for the synthesizer (spec §6.2)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from api.settings import get_settings
from google.genai import types
from pydantic import BaseModel, Field

from agents.jsonutil import strip_markdown_fences
from agents.vertex import vertex_client

log = logging.getLogger(__name__)

RAG_SYSTEM = (
    "You are a GCP documentation expert. Answer using ONLY the provided context chunks. "
    "For every claim, cite the source document and section in the citations array. "
    "Citation entries must be compact: reuse the chunk titles shown in headers like "
    "'Chunk i | DOCUMENT | section: …'; use \"unknown\" for the document title if missing. "
    "Never paste long context text inside citation JSON fields.\n"
    "Large retrieved excerpts are not authorization to ramble—the user may request "
    "unreasonable length (hundreds/thousands of lines); refuse that format politely but "
    "still summarize faithfully from snippets when facts exist.\n"
    "If the context lacks enough substantive material for what was asked, say so in answer. "
    "Do not hallucinate."
)


def _truncate_meta(s: Any, maxlen: int) -> str:
    if s is None:
        return ""
    t = " ".join(str(s).strip().split())
    if not t or t.lower() in ("none", "null", "n/a"):
        return ""
    if len(t) > maxlen:
        return t[: max(0, maxlen - 1)] + "…"
    return t


class RAGStructuredOut(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


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


_CHUNK_CHAR_LIMIT = 1500  # per-chunk text limit; 5 chunks × 1500 = ~7.5 KB context


def _hits_to_prompt(hits: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, h in enumerate(hits):
        doc = h.get("source_doc") or "unknown"
        sec = h.get("section") or ""
        text = (h.get("text") or "").strip()[:_CHUNK_CHAR_LIMIT]
        blocks.append(f"--- Chunk {i} | {doc} | section: {sec} ---\n{text}")
    return "\n\n".join(blocks) if blocks else "(no chunks retrieved)"


def _fallback_rag(query: str, hits: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    for i, h in enumerate(hits):
        citations.append(
            {
                "document": str(h.get("source_doc") or ""),
                "section": str(h.get("section") or ""),
                "chunk_id": str(i),
                "point_id": str(h.get("point_id") or ""),
            },
        )
    if not hits:
        return {
            "answer": "No documentation context was retrieved for this query.",
            "citations": [],
            "confidence": "low",
            "source": source,
        }
    preview = _hits_to_prompt(hits)[:6000]
    return {
        "answer": (
            f"(Offline summary) Relevant snippets for: {query.strip()[:500]!r}\n\n{preview}"
        ),
        "citations": citations,
        "confidence": "medium",
        "source": source,
    }


def _generate_rag_sync(
    *,
    query: str,
    context_block: str,
    model_id: str,
    project: str,
    location: str,
) -> str:
    client = vertex_client(project, location)
    user = f"User question:\n{query.strip()}\n\nRetrieved context:\n{context_block}"
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=RAG_SYSTEM,
        response_mime_type="application/json",
        response_schema=RAGStructuredOut,
        max_output_tokens=2048,
    )
    resp = client.models.generate_content(model=model_id, contents=user, config=cfg)
    text = _response_text(resp)
    if not text:
        raise RuntimeError("empty RAG model response")
    return text


def parse_rag_json(text: str) -> dict[str, Any]:
    data = json.loads(strip_markdown_fences(text))
    if not isinstance(data, dict):
        raise TypeError("RAG JSON must be an object")
    validated = RAGStructuredOut.model_validate(data)
    cites_raw = validated.citations
    cites: list[dict[str, Any]] = []
    for c in cites_raw:
        if not isinstance(c, dict):
            continue
        doc = _truncate_meta(c.get("document"), 260)
        sec = _truncate_meta(c.get("section"), 260)
        if not doc and not sec:
            continue
        entry: dict[str, Any] = {
            "document": doc if doc else "unknown",
            "section": sec,
        }
        for pk in ("chunk_id", "point_id"):
            if pk in c and c[pk] is not None:
                entry[pk] = str(c[pk])[:128]
        cites.append(entry)
    return {
        "answer": validated.answer,
        "citations": cites,
        "confidence": validated.confidence,
    }


async def run_rag_structured(query: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce RAG structured JSON (LLM when Vertex configured; else heuristic)."""
    settings = get_settings()
    project = settings.google_cloud_project
    if not project:
        return _fallback_rag(query, hits, source="fallback_no_gcp")

    ctx = _hits_to_prompt(hits)
    try:
        text = await asyncio.to_thread(
            _generate_rag_sync,
            query=query,
            context_block=ctx,
            model_id=settings.vertex_llm_model,
            project=project,
            location=settings.google_cloud_location,
        )
        out = parse_rag_json(text)
        out["source"] = "llm"
        return out
    except Exception:
        log.exception("RAG structured generation failed; using offline summary")
        return _fallback_rag(query, hits, source="fallback_parse")
