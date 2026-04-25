"""Code generation agent — **only** module that invokes ``code_exec_tool`` (spec §6.3)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from api.settings import get_settings
from google.genai import types
from pydantic import BaseModel, Field
from tools.code_exec_tool import exec_python

from agents.jsonutil import strip_markdown_fences
from agents.vertex import vertex_client

log = logging.getLogger(__name__)

CODE_MODEL_SYSTEM = (
    "You are a GCP developer expert. Generate clean, production-ready Python 3.12 samples.\n"
    "Always specify required dependencies aligned with google-cloud-* client libraries "
    "when relevant.\n"
    "The execution sandbox has **no network** and **no live GCP credentials** — note "
    "limits in `notes`.\n"
    "When a recent conversation block is included, treat follow-ups (e.g. changing a "
    "prior snippet, doubling a printed result) as referring to that context.\n"
    "Return JSON with keys: language (string, usually 'python'), code (string), "
    "explanation (string), dependencies (array of strings), notes (string), "
    "request_execution (boolean — true only when the user wants code to be run in "
    "the sandbox).\n"
    "No markdown fences."
)


class CodeGenJson(BaseModel):
    language: str = "python"
    code: str = Field(min_length=1)
    explanation: str = ""
    dependencies: list[str] = Field(default_factory=list)
    notes: str = ""
    request_execution: bool = True


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


def _generate_code_sync(*, user_blob: str, model_id: str, project: str, location: str) -> str:
    client = vertex_client(project, location)
    cfg = types.GenerateContentConfig(
        temperature=0,
        system_instruction=CODE_MODEL_SYSTEM,
        response_mime_type="application/json",
    )
    resp = client.models.generate_content(model=model_id, contents=user_blob, config=cfg)
    text = _response_text(resp)
    if not text:
        raise RuntimeError("empty code agent response")
    return text


def _execution_for_response(ex: dict[str, Any]) -> dict[str, Any] | None:
    """Map internal tool payload to §6.3 execution object (omit when not run)."""
    src = ex.get("source")
    if src == "skipped_no_key":
        return None
    if src == "validation_error":
        return None
    out = {
        "stdout": ex.get("stdout") or "",
        "stderr": ex.get("stderr") or "",
        "exit_code": ex.get("exit_code"),
    }
    return out


def _code_user_blob(question: str, conversation_context: str = "") -> str:
    q = (question or "").strip()
    cc = (conversation_context or "").strip()
    parts: list[str] = []
    if cc:
        parts.append(f"Recent conversation (earlier turns):\n{cc.strip()[:6000]}")
    parts.append(f"User question:\n{q}\n")
    return "\n\n".join(parts)


async def run_code_generation(
    question: str,
    conversation_context: str = "",
) -> dict[str, Any]:
    """Produce structured codegen JSON; optional E2B execution."""
    settings = get_settings()
    if not settings.google_cloud_project:
        return {
            "language": "python",
            "code": None,
            "explanation": "",
            "dependencies": [],
            "notes": "",
            "execution": None,
            "interpretation": "Vertex (GOOGLE_CLOUD_PROJECT) is required to generate code.",
            "source": "fallback_no_vertex",
        }

    user_blob = _code_user_blob(question, conversation_context)
    try:
        raw = await asyncio.to_thread(
            _generate_code_sync,
            user_blob=user_blob,
            model_id=settings.vertex_llm_model,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
        data = json.loads(strip_markdown_fences(raw))
        parsed = CodeGenJson.model_validate(data)
    except Exception as e:
        if log.isEnabledFor(logging.DEBUG):
            log.warning("Code agent generation failed: %s", e, exc_info=True)
        else:
            log.warning("Code agent generation failed: %s", e)
        return {
            "language": "python",
            "code": None,
            "explanation": "",
            "dependencies": [],
            "notes": str(e),
            "execution": None,
            "interpretation": f"Could not produce valid codegen JSON: {e}",
            "source": "fallback_parse",
        }

    notes = parsed.notes.strip()
    execution: dict[str, Any] | None = None
    interpretation = parsed.explanation.strip() or "Generated Python sample."

    if parsed.request_execution:
        ex = await exec_python(parsed.code)
        execution = _execution_for_response(ex)
        if ex.get("source") == "skipped_no_key":
            extra = (
                " E2B is not configured (E2B_API_KEY); execution was skipped." if not notes else ""
            )
            notes = f"{notes}{extra}".strip()
            interpretation = f"{interpretation} (execution skipped — no E2B API key)."
        elif ex.get("source") == "validation_error":
            interpretation = f"{interpretation} {ex.get('stderr', '')}".strip()
        elif ex.get("source") == "e2b_timeout":
            interpretation = (
                f"{interpretation} Sandbox or process hit the wall-clock limit "
                f"({settings.code_exec_wall_seconds}s)."
            )
        elif ex.get("source") not in ("e2b_ok", None):
            interpretation = f"{interpretation} Execution error: {ex.get('stderr', '')}".strip()

    return {
        "language": parsed.language,
        "code": parsed.code,
        "explanation": parsed.explanation,
        "dependencies": list(parsed.dependencies),
        "notes": notes,
        "execution": execution,
        "interpretation": interpretation,
        "source": "llm",
    }
