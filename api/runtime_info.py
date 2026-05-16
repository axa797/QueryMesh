"""Runtime capability summary (GCP optional vs Vertex path)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

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
    out["e2b_sandbox_configured"] = bool(
        (settings.e2b_api_key or "").strip(),
    )
    out["portal_jwt_configured"] = bool((settings.portal_jwt_secret or "").strip())
    cid = (settings.google_oauth_client_id or "").strip()
    csec = (settings.google_oauth_client_secret or "").strip()
    redir = (settings.google_oauth_redirect_uri or "").strip()
    front = (settings.portal_frontend_base_url or "").strip()
    out["oauth_env_configured"] = bool(cid and csec and redir and front)
    # Non-secret booleans: which OAuth-related settings resolved non-empty (debug prod without gcloud).
    out["oauth_env_present"] = {
        "google_oauth_client_id": bool(cid),
        "google_oauth_client_secret": bool(csec),
        "google_oauth_redirect_uri": bool(redir),
        "portal_frontend_base_url": bool(front),
    }
    if redir:
        out["oauth_redirect_origin"] = urlparse(redir).netloc or None
    if front:
        out["portal_frontend_origin"] = urlparse(front).netloc or None
    return out


def log_startup_capabilities(settings: Settings | None = None) -> None:
    s = settings if settings is not None else get_settings()
    cap = build_capabilities(s)
    log.info("querymesh startup %s", cap)
