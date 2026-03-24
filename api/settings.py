"""Application settings (env / .env)."""

from __future__ import annotations

from functools import lru_cache

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

    # §4 feature flag — prod on, local off
    rag_vertex_rerank: bool = False

    # BigQuery (§6.4; seed with scripts/bootstrap_bq.py)
    bigquery_project_id: str | None = None
    bigquery_dataset: str = "querymesh"
    bigquery_location: str = "US"


@lru_cache
def get_settings() -> Settings:
    return Settings()
