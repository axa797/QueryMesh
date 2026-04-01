"""Vector retrieval (Qdrant + Vertex embeddings; spec §6.2, §9)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from api.settings import get_settings
from ingestion.embeddings import embed_query_text
from qdrant_client import AsyncQdrantClient

log = logging.getLogger(__name__)

_TOP_K = 5
# RankRequest allows up to 200 records; cap Qdrant prefetch to stay under that and control cost.
_RERANK_POOL_CAP = 50
_CONTENT_CHAR_SOFT_CAP = 7500


def _vertex_rerank_records(
    *,
    query: str,
    hits: list[dict[str, Any]],
    project: str,
    top_n: int,
    model: str,
) -> list[dict[str, Any]]:
    """
    Discovery Engine semantic ranker (Vertex ranking API). On any error, returns ``hits`` unchanged
    (caller trims to ``top_n``).
    """
    if len(hits) <= 1:
        return hits
    try:
        from google.cloud import discoveryengine_v1 as discoveryengine
    except ImportError:
        log.warning("google-cloud-discoveryengine not installed; skipping rerank")
        return hits

    client = discoveryengine.RankServiceClient()
    ranking_config = client.ranking_config_path(
        project=project,
        location="global",
        ranking_config="default_ranking_config",
    )
    records: list = []
    for i, h in enumerate(hits):
        title = (h.get("section") or h.get("source_doc") or "doc")[:512]
        content = (h.get("text") or "")[:_CONTENT_CHAR_SOFT_CAP]
        records.append(
            discoveryengine.RankingRecord(
                id=str(i),
                title=title,
                content=content or title,
            )
        )
    t0 = time.monotonic()
    request = discoveryengine.RankRequest(
        ranking_config=ranking_config,
        model=model,
        top_n=top_n,
        query=query,
        records=records,
    )
    try:
        response = client.rank(request=request)
    except Exception:
        log.exception(
            "rag_rerank_fallback reason=api_error model=%s candidate_count=%s",
            model,
            len(hits),
        )
        return hits
    latency_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag_rerank_ok model=%s latency_ms=%s in=%s out=%s",
        model,
        latency_ms,
        len(hits),
        len(response.records),
    )
    by_id = {str(i): hits[i] for i in range(len(hits))}
    ordered: list[dict[str, Any]] = []
    for r in response.records:
        rec = by_id.get(r.id)
        if rec is not None:
            ordered.append({**rec, "rerank_score": r.score})
    if not ordered:
        log.warning("rag_rerank_fallback reason=empty_response")
        return hits
    return ordered


def _apply_vertex_rerank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    project: str,
    top_k: int,
    model: str,
) -> list[dict[str, Any]]:
    reranked = _vertex_rerank_records(
        query=query, hits=hits, project=project, top_n=top_k, model=model
    )
    out = reranked[:top_k]
    return out if out else hits[:top_k]


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

    want = top_k
    if settings.rag_vertex_rerank:
        pool = max(top_k, int(settings.rag_rerank_candidate_limit))
        want = min(_RERANK_POOL_CAP, pool)

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    try:
        resp = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=want,
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

    if not settings.rag_vertex_rerank:
        return hits[:top_k]

    try:
        ranked = await asyncio.to_thread(
            _apply_vertex_rerank,
            q,
            hits,
            project=project,
            top_k=top_k,
            model=(settings.vertex_ranking_model or "semantic-ranker-fast-004").strip(),
        )
    except Exception:
        log.exception("rag_rerank_fallback reason=unexpected")
        return hits[:top_k]
    return ranked
