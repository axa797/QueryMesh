"""Vector retrieval (Qdrant + Vertex embeddings; spec §6.2, §9)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from api.settings import get_settings
from ingestion.embeddings import embed_query_text
from qdrant_client import AsyncQdrantClient

log = logging.getLogger(__name__)

_TOP_K = 5


def _maybe_vertex_rerank(hits: list[dict[str, Any]], enabled: bool) -> list[dict[str, Any]]:
    if not enabled:
        return hits
    # Vertex AI reranker integration deferred (spec §6.2); flag reserved for prod.
    log.info("RAG_VERTEX_RERANK=true but Vertex reranker is not wired yet; returning Qdrant order.")
    return hits


async def retrieve_context(query: str, top_k: int = _TOP_K) -> list[dict[str, Any]]:
    """Dense retrieval: embed query (Vertex), search Qdrant (cosine), top ``top_k``."""
    q = (query or "").strip()
    if not q:
        return []

    settings = get_settings()
    project = settings.google_cloud_project
    if not project:
        log.warning("google_cloud_project unset; retrieval skipped")
        return []

    def _embed() -> list[float]:
        return embed_query_text(
            q,
            project=project,
            location=settings.google_cloud_location,
            model_id=settings.vertex_embedding_model,
        )

    try:
        vector = await asyncio.to_thread(_embed)
    except Exception:
        log.exception("Vertex query embedding failed")
        return []

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    try:
        resp = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
    except Exception:
        log.exception("Qdrant query failed for collection %s", settings.qdrant_collection)
        return []
    finally:
        await client.close()

    hits: list[dict[str, Any]] = []
    for pt in resp.points:
        payload = pt.payload or {}
        hits.append(
            {
                "text": payload.get("text", ""),
                "source_doc": payload.get("source_doc", ""),
                "section": payload.get("section", ""),
                "product": payload.get("product", ""),
                "page_number": payload.get("page_number"),
                "score": pt.score,
            }
        )

    return _maybe_vertex_rerank(hits, settings.rag_vertex_rerank)
