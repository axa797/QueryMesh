"""Synthesizer: user-facing message + optional ``save_memory`` (spec §6.5)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal
from uuid import UUID

from api.settings import get_settings
from google.genai import types
from memory.session import session_scope
from pydantic import BaseModel, Field
from tools.memory_tool import save_memory

from agents.jsonutil import strip_markdown_fences
from agents.vertex import vertex_client

log = logging.getLogger(__name__)

SYNTH_SYSTEM = (
    "You are a response synthesizer. You receive structured outputs from specialist agents. "
    "Combine them into a single coherent response for the end user.\n"
    "Preserve all citations from structured RAG JSON in your message (document + section). "
    "Do not add facts not present in the agent outputs.\n"
    "Use short sections if helpful.\n"
    "Return JSON with keys: message (string), save_memory (null or object with memory_type "
    "one of preference|context|history and content string). "
    "Only propose save_memory when the user clearly states a durable preference, fact, or "
    "context worth recalling later — omit save_memory otherwise."
)


class SaveMemoryBlock(BaseModel):
    memory_type: Literal["preference", "context", "history"]
    content: str = Field(min_length=1)


class SynthesisModel(BaseModel):
    message: str = Field(min_length=1)
    save_memory: SaveMemoryBlock | None = None


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


def _offline_synthesis(
    query: str,
    rag: dict[str, Any],
    *,
    memory_saved: bool,
) -> dict[str, Any]:
    ans = rag.get("answer") or ""
    cites = rag.get("citations") or []
    cite_lines = "\n".join(
        f"- {c.get('document')} / {c.get('section')}" for c in cites if isinstance(c, dict)
    )
    msg = f"{ans}\n\nSources:\n{cite_lines}" if cite_lines else ans
    return {
        "message": msg or f"(No synthesis) Query: {query[:500]}",
        "memory_saved": memory_saved,
        "memory_id": None,
        "source": "fallback_no_gcp",
    }


def _synth_payload(
    query: str,
    memory_compact: str,
    orchestrator: dict[str, Any],
    rag: dict[str, Any],
) -> str:
    mem = (memory_compact or "").strip()[:2000]
    orch = json.dumps(orchestrator, indent=2)[:4000]
    ragj = json.dumps(rag, indent=2)[:8000]
    return (
        f"User query:\n{query.strip()}\n\n"
        f"Long-term memory summary (context only):\n{mem or '(none)'}\n\n"
        f"Orchestrator plan:\n{orch}\n\n"
        f"Structured RAG JSON:\n{ragj}\n"
    )


def _generate_synth_sync(
    *,
    user_blob: str,
    model_id: str,
    project: str,
    location: str,
) -> str:
    client = vertex_client(project, location)
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=SYNTH_SYSTEM,
        response_mime_type="application/json",
    )
    resp = client.models.generate_content(model=model_id, contents=user_blob, config=cfg)
    text = _response_text(resp)
    if not text:
        raise RuntimeError("empty synthesizer model response")
    return text


async def run_synthesizer(
    query: str,
    memory_compact: str,
    orchestrator: dict[str, Any],
    rag_structured: dict[str, Any],
    user_id: UUID,
) -> dict[str, Any]:
    """LLM synthesis + optional ``save_memory`` in one JSON response."""
    settings = get_settings()
    project = settings.google_cloud_project
    user_blob = _synth_payload(query, memory_compact, orchestrator, rag_structured)

    memory_saved = False
    memory_id: str | None = None

    if not project:
        return _offline_synthesis(query, rag_structured, memory_saved=False)

    try:
        text = await asyncio.to_thread(
            _generate_synth_sync,
            user_blob=user_blob,
            model_id=settings.vertex_llm_model,
            project=project,
            location=settings.google_cloud_location,
        )
        data = json.loads(strip_markdown_fences(text))
        parsed = SynthesisModel.model_validate(data)
    except Exception:
        log.exception("Synthesizer LLM failed; using offline assembly")
        return _offline_synthesis(query, rag_structured, memory_saved=False)

    if parsed.save_memory is not None:
        try:
            async with session_scope() as session:
                mid = await save_memory(
                    session,
                    user_id,
                    memory_type=parsed.save_memory.memory_type,
                    content=parsed.save_memory.content,
                )
            memory_saved = True
            memory_id = str(mid)
        except Exception:
            log.exception("save_memory failed; returning message without persist")

    return {
        "message": parsed.message,
        "memory_saved": memory_saved,
        "memory_id": memory_id,
        "source": "llm",
    }
