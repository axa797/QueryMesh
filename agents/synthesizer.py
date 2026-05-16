"""Synthesizer: user-facing message + optional ``save_memory`` (spec §6.5)."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
import time
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
    "When document retrieval was not used for this turn, never tell the user that "
    '"retrieval was not routed" or that search was skipped—those are internal pipeline '
    "signals, not user-facing language. Answer the question naturally using only what matters "
    "(e.g. code or analytics results).\n"
    "Recent conversation is provided as context—use it implicitly; do not dump the thread "
    'verbatim or label it "Earlier turns".\n'
    "Do NOT append a Sources/References/Citations section to `message` and do NOT paste "
    "long bullet lists of excerpts—retrieval excerpts are shown in the product UI separately.\n"
    "When RAG cites documents, briefly name them inline (one short clause) only if helpful.\n"
    "When Analytics data includes tables or metrics, summarize counts and headline values.\n"
    "When Code agent output describes code or execution results, summarize in prose "
    "(optionally quote at most one ~2-line snippet).\n"
    "If the Code agent JSON includes ``execution.stdout`` and the user asked for the result of "
    "running the code, a count, or \"only the final output\", lead ``message`` with that stdout "
    "verbatim (trimmed). One short sentence of prose may follow; do not replace the answer with "
    "an ellipsis or a truncated partial code listing.\n"
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

# Pipeline placeholder when RAG is skipped; the model must not echo it—strip defensively.
_SKIPPED_RAG_NOTICE = re.compile(
    r"(?is)(?:^|\n)\s*Retrieval was not routed for this query\.\s*"
)


def finalize_synthesis_display_message(raw: str) -> str:
    """Keep answer prose; drop pipeline boilerplate and trailing Sources/Reference dumps."""
    t = _SKIPPED_RAG_NOTICE.sub("\n", raw)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t:
        return raw
    m = _REF_BLOCK_HEADING.search(t)
    if not m:
        return t
    head = t[: m.start()].rstrip()
    if head.strip():
        return head
    return "Details are summarized in the source list below."


def _parse_execution_stdout(code_structured: Any) -> str | None:
    """Return trimmed stdout from Code agent ``execution`` when present."""
    if not isinstance(code_structured, dict):
        return None
    ex = code_structured.get("execution")
    ej: dict[str, Any] | None = None
    if isinstance(ex, dict):
        ej = ex
    elif isinstance(ex, str) and ex.strip():
        try:
            parsed = json.loads(ex)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(ex)
            except (ValueError, SyntaxError):
                parsed = None
        ej = parsed if isinstance(parsed, dict) else None
    if not isinstance(ej, dict) or ej.get("stdout") is None:
        return None
    raw = str(ej.get("stdout", "")).strip()
    return raw if raw else None


def _mask_stream_partial_with_stdout(stdout_anchor: str | None, display: str) -> str:
    """While JSON streams, show stable stdout when provisional prose diverges from it.

    Provisional `message` extraction often grows through long code-like text before the
    model finishes a short stdout answer; non-streaming already returns the correct
    final message. Masking avoids flashing misleading partial text in the UI.
    """
    if not stdout_anchor:
        return display
    o = stdout_anchor.strip()
    if not o:
        return display
    d = display.strip()
    if not d:
        return o
    if d.startswith(o) or o.startswith(d):
        return display
    return o


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
    # Chunks may be (a) repeated growing full-text snapshots, (b) token deltas, or both.
    # Vertex streaming often sends non-prefix snapshots after a delta; assigning
    # ``longest = piece`` corrupts JSON and breaks provisional ``message`` extraction.
    _DBG = "/Users/user/Desktop/Code/querymesh/.cursor/debug-245362.log"
    _chunk_n = 0
    _partial_emits = 0
    _last_snap: dict[str, Any] | None = None
    for resp in stream:
        piece = _response_text(resp)
        if not piece:
            continue
        prev_longest = longest
        if not longest:
            merged = piece
        elif piece.startswith(longest):
            merged = piece
        elif longest.startswith(piece):
            merged = longest
        else:
            merged = longest + piece
        longest = merged
        _chunk_n += 1
        provisional = provisional_json_message_field(longest)
        _prov_fin = (
            finalize_synthesis_display_message(provisional) if provisional else ""
        )
        # region agent log
        _snap = {
            "chunk": _chunk_n,
            "len_piece": len(piece),
            "len_prev_longest": len(prev_longest),
            "piece_extends_prev": (not prev_longest or piece.startswith(prev_longest)),
            "prev_extends_piece": bool(prev_longest and prev_longest.startswith(piece)),
            "merge_mode": (
                "init"
                if not prev_longest
                else (
                    "prefix_snap"
                    if piece.startswith(prev_longest)
                    else (
                        "keep_longer"
                        if prev_longest.startswith(piece)
                        else "append_delta"
                    )
                )
            ),
            "msg_key_i": longest.find('"message"'),
            "prov_len": len(_prov_fin) if _prov_fin else 0,
            "prov_head": (_prov_fin or "")[:160],
        }
        _last_snap = _snap
        if _chunk_n <= 6:
            try:
                with open(_DBG, "a", encoding="utf-8") as _df:
                    _df.write(
                        json.dumps(
                            {
                                "sessionId": "245362",
                                "runId": "stream-synth",
                                "hypothesisId": "H1",
                                "location": "agents/synthesizer.py:_stream_generate_json_sync",
                                "message": "stream_chunk_sample",
                                "data": _snap,
                                "timestamp": int(time.time() * 1000),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError:
                pass
        # endregion agent log
        if provisional and synthesis_partial_sink:
            synthesis_partial_sink(provisional)
            _partial_emits += 1

    # region agent log
    if _last_snap is not None:
        try:
            with open(_DBG, "a", encoding="utf-8") as _df:
                _df.write(
                    json.dumps(
                        {
                            "sessionId": "245362",
                            "runId": "stream-synth",
                            "hypothesisId": "H1",
                            "location": "agents/synthesizer.py:_stream_generate_json_sync",
                            "message": "stream_final",
                            "data": {
                                **_last_snap,
                                "total_chunks": _chunk_n,
                                "partial_sink_calls": _partial_emits,
                                "len_acc": len(longest),
                            },
                            "timestamp": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass
    # endregion agent log

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
            _stdout_anchor = _parse_execution_stdout(code_structured)
            _mask_logged = False

            def bridged_sink(m: str) -> None:
                nonlocal _mask_logged
                fm = finalize_synthesis_display_message(m)
                masked = _mask_stream_partial_with_stdout(_stdout_anchor, fm)
                if _stdout_anchor and masked != fm and not _mask_logged:
                    _mask_logged = True
                    try:
                        with open(
                            "/Users/user/Desktop/Code/querymesh/.cursor/debug-245362.log",
                            "a",
                            encoding="utf-8",
                        ) as _df:
                            _df.write(
                                json.dumps(
                                    {
                                        "sessionId": "245362",
                                        "hypothesisId": "H6",
                                        "runId": "post-fix",
                                        "location": "agents/synthesizer.py:bridged_sink",
                                        "message": "stream_stdout_mask_applied",
                                        "data": {
                                            "fm_head": fm[:120],
                                            "masked_head": masked[:120],
                                        },
                                        "timestamp": int(time.time() * 1000),
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except OSError:
                        pass
                loop.call_soon_threadsafe(
                    partial(
                        synthesis_partial_sink,
                        masked,
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

    # region agent log
    try:
        _px = _parse_execution_stdout(code_structured)
        _stdout_hint = _px[:40] if _px else ""
        _agent_log = {
            "sessionId": "245362",
            "hypothesisId": "FIX_VERIF",
            "location": "agents/synthesizer.py:run_synthesizer",
            "message": "synthesis_out_vs_stdout",
            "data": {
                "stdout_preview": _stdout_hint,
                "msg_len": len(msg_out),
                "msg_leads_digit": bool(msg_out.strip() and msg_out.strip()[0].isdigit()),
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(
            "/Users/user/Desktop/Code/querymesh/.cursor/debug-245362.log",
            "a",
            encoding="utf-8",
        ) as _lf:
            _lf.write(json.dumps(_agent_log, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # endregion agent log

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
