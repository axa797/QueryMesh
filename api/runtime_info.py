"""Runtime capability summary (GCP optional vs Vertex path)."""

from __future__ import annotations

import logging
from typing import Any

from api.settings import Settings, get_settings

log = logging.getLogger(__name__)


def probe_application_default_credentials() -> bool:
    try:
        import google.auth
    except ImportError:
        return False
    try:
        creds, _ = google.auth.default()
    except Exception:
        return False
    return creds is not None


def build_capabilities(settings: Settings) -> dict[str, Any]:
    has_vertex = bool(settings.google_cloud_project)
    adc_ok: bool | None = None
    if has_vertex:
        adc_ok = probe_application_default_credentials()

    out: dict[str, Any] = {
        "runtime_mode": "vertex" if has_vertex else "local",
        "vertex_project_configured": has_vertex,
        "application_default_credentials_ok": adc_ok,
    }
    if not has_vertex:
        out["self_hosted_stack_ok"] = True
        out["vertex_features_offline"] = [
            "orchestrator_routing",
            "rag_structured_llm",
            "synthesizer_llm",
            "query_embeddings_retrieval",
            "ingestion_embeddings",
            "analytics_sql_llm",
            "code_generation",
        ]
    elif adc_ok is False:
        out["local_fallback_hint"] = (
            "Unset GOOGLE_CLOUD_PROJECT for heuristic local mode, or run "
            "'gcloud auth application-default login' with a valid project."
        )
    return out


def log_startup_capabilities(settings: Settings | None = None) -> None:
    s = settings if settings is not None else get_settings()
    cap = build_capabilities(s)
    log.info("querymesh startup %s", cap)
