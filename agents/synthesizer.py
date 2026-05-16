"""Synthesizer: user-facing message + optional ``save_memory`` (spec §6.5)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from functools import partial
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
    "The JSON field `message` must be readable natural language only.\n"
    "Do NOT copy internal prompt labels such as 'Earlier turns', 'Orchestrator plan', "
    "'Structured RAG JSON', 'Code agent JSON', or 'Analytics JSON'.\n"
    "Do NOT paste large raw JSON payloads from structured inputs.\n"
    "Recent conversation is provided as context—use it implicitly; do not dump the thread "
    'verbatim or label it "Earlier turns".\n'
    "Do NOT append a Sources/References/Citations section to `message` and do NOT paste "
    "long bullet lists of excerpts—retrieval excerpts are shown in the product UI separately.\n"
    "When RAG cites documents, briefly name them inline (one short clause) only if helpful.\n"
    "When Analytics data includes tables or metrics, summarize counts and headline values.\n"
    "When Code agent output describes code or execution results, summarize in prose "
    "(optionally quote at most one ~2-line snippet).\n"
    "Do not add facts not present in the agent outputs.\n"
    "Return JSON with keys: message (string), save_memory (null or object with memory_type "
    "one of preference|context|history and content string).\n"
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


# Strip citation dumps appended after the substantive answer—the UI renders source_cards.
_REF_BLOCK_HEADING = re.compile(
    r"(?is)(?:^|\n)\s*\*{0,2}\s*(?:Sources|References|Citations)"
    r"\s*\*{0,2}\s*:\s*[\s\S]*",
)


def finalize_synthesis_display_message(raw: str) -> str:
    """Keep answer prose; drop trailing Sources/Reference bullet dumps."""
    t = raw.strip()
    if not t:
        return raw
    m = _REF_BLOCK_HEADING.search(raw)
    if not m:
        return raw
    head = raw[: m.start()].rstrip()
    if head.strip():
        return head
    return "Details are summarized in the source list below."


def _offline_analytics_digest(analytics: dict[str, Any] | None) -> str:
    if not analytics or analytics.get("source") in (None, "skipped"):
        return ""
    inter = str(analytics.get("interpretation") or "").strip()
    if inter:
        return inter[:2000].strip()
    return ""


def _offline_code_digest(code: dict[str, Any] | None) -> str:
    if not code or code.get("source") in (None, "skipped"):
        return ""
    inter = str(code.get("interpretation") or "").strip()
    lang = str(code.get("language") or "").strip()
    snippet = code.get("code")
    excerpt = ""
    if isinstance(snippet, str):
        flat = " ".join(snippet.strip().split())
        if flat:
            excerpt = flat[:420] + ("…" if len(flat) > 420 else "")
    bits: list[str] = []
    if inter:
        bits.append(inter[:1500])
    if excerpt:
        hdr = lang or "text"
        bits.append(f"({hdr}) {excerpt}")
    return "\n".join(bits).strip()


def _offline_synthesis(
    query: str,
    rag: dict[str, Any],
    analytics: dict[str, Any] | None,
    code: dict[str, Any] | None,
    *,
    memory_saved: bool,
    conversation_context: str = "",
) -> dict[str, Any]:
    ans = rag.get("answer") or ""
    parts: list[str] = []
    if ans.strip():
        parts.append(ans.strip())

    ada = _offline_analytics_digest(analytics)
    if ada:
        parts.append(ada)
    cod = _offline_code_digest(code)
    if cod:
        parts.append(cod)

    msg = "\n\n".join(parts) if parts else ""
    cc = (conversation_context or "").strip()
    # Avoid dumping numbered chat blobs into the UI; LLM synthesis path merges history.
    if not msg.strip() and cc:
        tail = cc.replace("\r\n", "\n").split("\n")[0][:400].strip()
        if tail:
            msg = tail
    if not msg:
        msg = f"(No synthesis) Query: {query[:500]}"
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
    analytics: dict[str, Any] | None,
    code: dict[str, Any] | None,
    conversation_context: str = "",
) -> str:
    mem = (memory_compact or "").strip()[:2000]
    cc = (conversation_context or "").strip()[:8000]
    orch = json.dumps(orchestrator, indent=2)[:4000]
    ragj = json.dumps(rag, indent=2)[:8000]
    aj = json.dumps(analytics or {}, indent=2)[:8000]
    cj = json.dumps(code or {}, indent=2)[:8000]
    return (
        f"User query:\n{query.strip()}\n\n"
        f"Recent conversation (earlier turns only):\n{cc or '(none)'}\n\n"
        f"Long-term memory summary (context only):\n{mem or '(none)'}\n\n"
        f"Orchestrator plan:\n{orch}\n\n"
        f"Structured RAG JSON:\n{ragj}\n\n"
        f"Structured Analytics JSON:\n{aj}\n\n"
        f"Structured Code agent JSON:\n{cj}\n"
    )


def provisional_json_message_field(acc: str) -> str | None:
    """Best-effort extraction of JSON ``message`` while the model streams ``application/json``."""
    key = '"message"'
    ki = acc.find(key)
    if ki == -1:
        return None
    colon = acc.find(":", ki + len(key))
    if colon == -1:
        return None
    i = colon + 1
    while i < len(acc) and acc[i] in " \t\n\r":
        i += 1
    if i >= len(acc) or acc[i] != '"':
        return None
    i += 1
    chars: list[str] = []
    while i < len(acc):
        c = acc[i]
        if c == "\\":
            if i + 1 >= len(acc):
                return "".join(chars) if chars else None
            n = acc[i + 1]
            esc = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
            chars.append(esc.get(n, n))
            i += 2
            continue
        if c == '"':
            return "".join(chars)
        chars.append(c)
        i += 1
    return "".join(chars) if chars else None


def _stream_generate_json_sync(
    *,
    user_blob: str,
    model_id: str,
    project: str,
    location: str,
    synthesis_partial_sink: Callable[[str], None] | None,
) -> str:
    client = vertex_client(project, location)
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=SYNTH_SYSTEM,
        response_mime_type="application/json",
    )
    longest = ""

    stream = client.models.generate_content_stream(
        model=model_id,
        contents=user_blob,
        config=cfg,
    )
    # Stream chunks expose monotonically growing concatenated JSON text per SDK.
    for resp in stream:
        piece = _response_text(resp)
        if not piece:
            continue
        if len(piece) < len(longest):
            continue
        longest = piece
        provisional = provisional_json_message_field(longest)
        if provisional and synthesis_partial_sink:
            synthesis_partial_sink(provisional)

    if not longest:
        raise RuntimeError("empty streamed synthesizer model response")
    return longest


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
    analytics_structured: dict[str, Any] | None,
    code_structured: dict[str, Any] | None,
    user_id: UUID,
    conversation_context: str = "",
    *,
    synthesis_partial_sink: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """LLM synthesis + optional ``save_memory`` in one JSON response."""
    settings = get_settings()
    project = settings.google_cloud_project
    user_blob = _synth_payload(
        query,
        memory_compact,
        orchestrator,
        rag_structured,
        analytics_structured,
        code_structured,
        conversation_context,
    )

    memory_saved = False
    memory_id: str | None = None

    if not project:
        out_no_gcp = _offline_synthesis(
            query,
            rag_structured,
            analytics_structured,
            code_structured,
            memory_saved=False,
            conversation_context=conversation_context,
        )
        out_no_gcp["message"] = finalize_synthesis_display_message(out_no_gcp["message"])
        if synthesis_partial_sink:
            synthesis_partial_sink(out_no_gcp["message"])
        return out_no_gcp

    try:
        if synthesis_partial_sink is not None:
            loop = asyncio.get_running_loop()

            def bridged_sink(m: str) -> None:
                loop.call_soon_threadsafe(
                    partial(
                        synthesis_partial_sink,
                        finalize_synthesis_display_message(m),
                    ),
                )

            text = await asyncio.to_thread(
                _stream_generate_json_sync,
                user_blob=user_blob,
                model_id=settings.vertex_llm_model,
                project=project,
                location=settings.google_cloud_location,
                synthesis_partial_sink=bridged_sink,
            )
        else:
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
        fb = _offline_synthesis(
            query,
            rag_structured,
            analytics_structured,
            code_structured,
            memory_saved=False,
            conversation_context=conversation_context,
        )
        fb["message"] = finalize_synthesis_display_message(fb["message"])
        if synthesis_partial_sink:
            synthesis_partial_sink(fb["message"])
        return fb

    msg_out = finalize_synthesis_display_message(parsed.message)

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
        "message": msg_out,
        "memory_saved": memory_saved,
        "memory_id": memory_id,
        "source": "llm",
    }
