"""Application settings (env / .env)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _optional_nonempty_str(v: object) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    api_key_pepper: str
    redis_url: str

    # Optional: POST /account/register|login + API key minting (browser/session JWT).
    portal_jwt_secret: str | None = None
    portal_jwt_ttl_hours: int = 168

    # GCP / RAG (§9, §15.8)
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    # text-embedding-004 was retired 2026-01-14; 005 is the current English/code workhorse.
    vertex_embedding_model: str = "text-embedding-005"
    # Vertex publisher id; must match a model available in GOOGLE_CLOUD_LOCATION.
    vertex_llm_model: str = "gemini-2.5-flash"

    # Qdrant (local: docker-compose)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "gcp_docs"

    # Ingestion API: document directory for `source=gcp_docs`
    ingestion_gcp_docs_dir: str = ""
    ingestion_recreate_collection: bool = False

    # §4 feature flag — Discovery Engine ranker after dense retrieval (enable API on project).
    rag_vertex_rerank: bool = True
    # When rerank on: retrieve at least this many dense hits before semantic rank → top_k
    rag_rerank_candidate_limit: int = 20
    # If set: skip Vertex rerank when the best dense (Qdrant) score is below this threshold.
    # Off by default so behavior matches historical “always rerank when flag on”.
    rag_rerank_min_dense_score: float | None = None
    # Discovery Engine Rank API model (spec §6.2; requires Discovery Engine API enabled)
    vertex_ranking_model: str = "semantic-ranker-fast-004"

    # BigQuery analytics agent
    bigquery_project_id: str | None = None
    bigquery_dataset: str = "querymesh"
    bigquery_location: str = "US"

    # Rate limiting (slowapi; default same Redis as sessions)
    query_rate_limit: str = "60/minute"
    rate_limit_storage_uri: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_tracing_environment: str | None = Field(
        default=None,
        description="Langfuse trace environment tag (e.g. production).",
    )

    # Optional CORS (e.g. open demo HTML from file:// or another dev port)
    cors_allow_origins: str | None = Field(
        default=None,
        description="Comma-separated origins, or * for any (demo/local only).",
    )

    # E2B / code execution (§6.3, §15.12) — optional locally.
    # template: unset → SDK default (same as Sandbox.create() with no template arg).
    # Set E2B_TEMPLATE_ID after `e2b template build` for the custom image (e2b/Dockerfile).
    e2b_api_key: str | None = None
    e2b_template_id: str | None = None
    e2b_sandbox_timeout_seconds: int = 120
    code_exec_wall_seconds: float = 15.0
    code_exec_output_max_bytes: int = 65536
    code_exec_max_concurrent: int = 2
    code_exec_max_code_chars: int = 200_000

    # LangGraph checkpointed messages: cap how many tail messages format into prompts.
    graph_message_history_max: int = 10

    @field_validator(
        "google_cloud_project",
        "bigquery_project_id",
        "qdrant_api_key",
        "e2b_api_key",
        "e2b_template_id",
        "portal_jwt_secret",
        mode="before",
    )
    @classmethod
    def _blank_optional_str(cls, v: object) -> str | None:
        return _optional_nonempty_str(v)


def _dotenv_mtime() -> float | None:
    """Mtime of project `.env` if present; used to invalidate settings after edits."""
    p = Path(".env")
    try:
        return p.stat().st_mtime_ns if p.is_file() else None
    except OSError:
        return None


_settings_cache: Settings | None = None
_settings_mtime_key: float | None = None


class _GetSettings:
    """Callable settings singleton; reloads when ``.env`` file changes on disk."""

    __slots__ = ()

    def __call__(self) -> Settings:
        global _settings_cache, _settings_mtime_key
        m = _dotenv_mtime()
        if _settings_cache is not None and m == _settings_mtime_key:
            return _settings_cache
        _settings_cache = Settings()
        _settings_mtime_key = m
        return _settings_cache

    def cache_clear(self) -> None:
        """Drop cached ``Settings`` (tests; env-only updates without ``.env``)."""
        global _settings_cache, _settings_mtime_key
        _settings_cache = None
        _settings_mtime_key = None


get_settings = _GetSettings()
