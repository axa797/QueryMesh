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
    "If the context does not contain enough information, say so explicitly in answer. "
    "Do not hallucinate."
)


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


def _hits_to_prompt(hits: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, h in enumerate(hits):
        doc = h.get("source_doc") or "unknown"
        sec = h.get("section") or ""
        text = (h.get("text") or "").strip()[:4000]
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
    return {
        "answer": validated.answer,
        "citations": list(validated.citations),
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
