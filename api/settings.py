"""Application settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    api_key_pepper: str
    redis_url: str

    # GCP / RAG (§9, §15.8)
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    vertex_embedding_model: str = "text-embedding-004"
    vertex_llm_model: str = "gemini-2.0-flash"

    # Qdrant (local: docker-compose)
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "gcp_docs"

    # Ingestion API (Phase 15): document directory for `source=gcp_docs`
    ingestion_gcp_docs_dir: str = ""
    ingestion_recreate_collection: bool = False

    # §4 feature flag — prod on, local off
    rag_vertex_rerank: bool = False
    # When rerank on: retrieve at least this many dense hits before semantic rank → top_k
    rag_rerank_candidate_limit: int = 20
    # Discovery Engine Rank API model (spec §6.2; requires Discovery Engine API enabled)
    vertex_ranking_model: str = "semantic-ranker-fast-004"

    # BigQuery (§6.4; seed with scripts/bootstrap_bq.py)
    bigquery_project_id: str | None = None
    bigquery_dataset: str = "querymesh"
    bigquery_location: str = "US"

    # Rate limiting (Phase 14 — slowapi; default same Redis as sessions)
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

    # E2B / code execution (§6.3, §15.12) — optional locally
    e2b_api_key: str | None = None
    e2b_template_id: str = "querymesh-code"
    e2b_sandbox_timeout_seconds: int = 120
    code_exec_wall_seconds: float = 15.0
    code_exec_output_max_bytes: int = 65536
    code_exec_max_concurrent: int = 2
    code_exec_max_code_chars: int = 200_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
