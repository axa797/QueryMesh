"""Langfuse tracing setup for LangGraph (spec §5 instrumentation, §11 Phase 13)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from api.settings import get_settings
from langfuse import Langfuse, get_client

log = logging.getLogger(__name__)


def langfuse_enabled() -> bool:
    s = get_settings()
    pk = (s.langfuse_public_key or "").strip()
    sk = (s.langfuse_secret_key or "").strip()
    return bool(pk and sk)


def _ensure_client() -> None:
    """Register singleton so ``CallbackHandler``'s ``get_client`` is authenticated."""
    s = get_settings()
    Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
    )


def build_langgraph_invoke_config(
    *,
    thread_id: str,
    session_id: str,
) -> tuple[dict[str, Any], str]:
    """
    LangGraph config for ``ainvoke`` including optional Langfuse callbacks.

    Returns ``(config, trace_id)`` — ``trace_id`` is new UUID hex each call for correlation
    (Langfuse also records nested spans for each node / LLM).
    """
    trace_id = uuid.uuid4().hex
    base: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "langfuse_session_id": session_id,
            "thread_id": thread_id,
        },
    }
    if not langfuse_enabled():
        return base, trace_id

    try:
        from langfuse.langchain import CallbackHandler
    except ModuleNotFoundError:
        log.warning("langfuse.langchain unavailable; skipping Langfuse callbacks")
        return base, trace_id

    _ensure_client()
    s = get_settings()
    handler = CallbackHandler(
        public_key=s.langfuse_public_key,
        trace_context={"trace_id": trace_id},
    )
    base["callbacks"] = [handler]
    return base, trace_id


def flush_langfuse() -> None:
    """Best-effort flush after a request (short-lived workers)."""
    if not langfuse_enabled():
        return
    try:
        s = get_settings()
        get_client(public_key=s.langfuse_public_key).flush()
    except Exception:
        log.debug("Langfuse flush failed", exc_info=True)
