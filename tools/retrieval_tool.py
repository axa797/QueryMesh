"""Vector retrieval (Qdrant + Vertex embeddings; spec §6.2, §9)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from api.settings import get_settings
from ingestion.embeddings import embed_query_text

log = logging.getLogger(__name__)

_TOP_K = 5
# RankRequest allows up to 200 records; cap Qdrant prefetch to stay under that and control cost.
_RERANK_POOL_CAP = 50
_CONTENT_CHAR_SOFT_CAP = 7500
_HYBRID_PREFETCH_CAP = 80
_rrf_base = 60

_LEX_SKIP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "how",
        "are",
        "was",
        "has",
        "have",
        "does",
        "did",
        "can",
        "will",
        "into",
        "about",
        "your",
        "their",
        "they",
        "when",
        "which",
        "who",
        "whom",
        "also",
        "not",
        "but",
        "its",
        "use",
        "using",
        "used",
        "new",
        "any",
        "all",
        "each",
        "than",
        "then",
        "such",
        "may",
        "more",
        "most",
        "some",
        "other",
        "many",
        "both",
        "was",
        "were",
        "been",
        "being",
        "off",
        "out",
        "per",
        "via",
        "than",
        "over",
        "between",
        "during",
        "after",
        "before",
        "under",
        "again",
        "here",
        "there",
        "where",
        "why",
        "who",
        "well",
        "just",
        "only",
        "same",
        "very",
        "too",
        "does",
        "did",
        "had",
        "his",
        "her",
        "she",
        "him",
        "our",
        "you",
        "your",
        "they",
        "them",
        "these",
        "those",
        "upon",
        "once",
        "ever",
        "even",
        "much",
        "must",
        "might",
        "shall",
        "should",
        "could",
        "would",
    }
)


def _vertex_rerank_preflight_skip_reason(
    hits: list[dict[str, Any]],
    *,
    min_dense_score: float | None,
) -> str | None:
    """Return skip reason or None if rerank may proceed (subject to API)."""
    if len(hits) < 2:
        return "few_candidates"
    if min_dense_score is None:
        return None
    top = hits[0].get("score")
    if top is None:
        return None
    if float(top) < float(min_dense_score):
        return "low_dense_score"
    return None


def _order_signature(hits: list[dict[str, Any]], k: int) -> tuple[tuple[str, str, str], ...]:
    """Stable per-hit identity for comparing dense vs reranked top-k order."""
    out: list[tuple[str, str, str]] = []
    for h in hits[:k]:
        out.append(
            (
                str(h.get("source_doc") or ""),
                str(h.get("section") or ""),
                (str(h.get("text") or ""))[:120],
            )
        )
    return tuple(out)


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


def _lex_query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in re.findall(r"[a-z0-9]+", query.lower()):
        if len(t) <= 2 or t in _LEX_SKIP or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= 28:
            break
    return out


def _lexical_term_hits_blob(text: str, terms: list[str]) -> int:
    if not terms:
        return 0
    blob = (text or "").lower()
    hits = 0
    for t in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", blob):
            hits += 1
    return hits


def _reciprocal_rank_fusion(rankings: list[list[int]], *, k: int) -> list[int]:
    scores: dict[int, float] = {}
    for rlist in rankings:
        for pos, idx in enumerate(rlist):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return sorted(scores.keys(), key=lambda ix: (-scores[ix], ix))


def _apply_lexical_rrf(hits: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
    if len(hits) < 3 or len(terms) < 2:
        return hits
    n = len(hits)
    dense_order = list(range(n))
    lex_scored = [
        (i, _lexical_term_hits_blob(str(hits[i].get("text") or ""), terms)) for i in range(n)
    ]
    lex_scored.sort(key=lambda x: (-x[1], x[0]))
    lexical_order = [i for i, _ in lex_scored]
    fused = _reciprocal_rank_fusion([dense_order, lexical_order], k=_rrf_base)
    return [hits[i] for i in fused]


async def retrieve_context(
    query: str, top_k: int = _TOP_K
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dense retrieval (and optional lexical RRF) → hits + timing/meta for telemetry."""
    meta: dict[str, Any] = {
        "retrieve_embed_ms": 0,
        "retrieve_qdrant_ms": 0,
        "retrieve_vertex_rerank_ms": 0,
        "dense_prefetch_count": 0,
        "retrieval_returned_count": 0,
        "hybrid_lexical_rrf": False,
        "rerank_skip_reason": None,
        "rerank_order_changed": None,
    }
    q = (query or "").strip()
    if not q:
        meta["retrieve_total_ms"] = 0
        return [], meta

    def _finalize_return(
        out_hits: list[dict[str, Any]], m: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        m["retrieve_total_ms"] = (
            int(m.get("retrieve_embed_ms") or 0)
            + int(m.get("retrieve_qdrant_ms") or 0)
            + int(m.get("retrieve_vertex_rerank_ms") or 0)
        )
        return out_hits, m

    settings = get_settings()
    project = settings.google_cloud_project
    if not project:
        log.warning("google_cloud_project unset; retrieval skipped")
        return _finalize_return([], meta)

    embed_t0 = time.monotonic()

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
        meta["retrieve_embed_ms"] = int((time.monotonic() - embed_t0) * 1000)
        return _finalize_return([], meta)
    meta["retrieve_embed_ms"] = int((time.monotonic() - embed_t0) * 1000)

    base_want = top_k
    if settings.rag_vertex_rerank:
        pool = max(top_k, int(settings.rag_rerank_candidate_limit))
        base_want = min(_RERANK_POOL_CAP, pool)

    want = base_want
    terms = _lex_query_terms(q)
    if settings.rag_hybrid_lexical and len(terms) >= 2:
        want = min(_HYBRID_PREFETCH_CAP, max(base_want, base_want * 8))

    qdr_t0 = time.monotonic()

    def _qdrant_query() -> list[dict[str, Any]]:
        import httpx

        base = (settings.qdrant_url or "").strip().rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key.strip()
        body = {
            "vector": vector,
            "limit": want,
            "with_payload": True,
        }
        with httpx.Client(timeout=settings.qdrant_timeout_seconds) as client:
            r = client.post(
                f"{base}/collections/{settings.qdrant_collection}/points/search",
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        raw = data.get("result")
        return raw if isinstance(raw, list) else []

    try:
        scored = await asyncio.to_thread(_qdrant_query)
    except Exception:
        meta["retrieve_qdrant_ms"] = int((time.monotonic() - qdr_t0) * 1000)
        log.exception("Qdrant query failed for collection %s", settings.qdrant_collection)
        return _finalize_return([], meta)

    meta["retrieve_qdrant_ms"] = int((time.monotonic() - qdr_t0) * 1000)

    hits: list[dict[str, Any]] = []
    for pt in scored:
        if not isinstance(pt, dict):
            continue
        payload = pt.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        hits.append(
            {
                "text": payload.get("text", ""),
                "source_doc": payload.get("source_doc", ""),
                "section": payload.get("section", ""),
                "product": payload.get("product", ""),
                "page_number": payload.get("page_number"),
                "score": pt.get("score"),
                "point_id": str(pt.get("id", "")),
            }
        )

    meta["dense_prefetch_count"] = len(hits)

    if settings.rag_hybrid_lexical and len(terms) >= 2 and len(hits) >= 3:
        hits = _apply_lexical_rrf(hits, terms)
        meta["hybrid_lexical_rrf"] = True

    if not settings.rag_vertex_rerank:
        final = hits[:top_k]
        meta["retrieval_returned_count"] = len(final)
        return _finalize_return(final, meta)

    skip = _vertex_rerank_preflight_skip_reason(
        hits, min_dense_score=settings.rag_rerank_min_dense_score
    )
    if skip:
        log.info(
            "rag_rerank_skip reason=%s candidate_count=%s top_score=%s min_dense=%s",
            skip,
            len(hits),
            hits[0].get("score") if hits else None,
            settings.rag_rerank_min_dense_score,
        )
        meta["rerank_skip_reason"] = skip
        final = hits[:top_k]
        meta["retrieval_returned_count"] = len(final)
        return _finalize_return(final, meta)

    rr_t0 = time.monotonic()
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
        meta["retrieve_vertex_rerank_ms"] = int((time.monotonic() - rr_t0) * 1000)
        final = hits[:top_k]
        meta["retrieval_returned_count"] = len(final)
        return _finalize_return(final, meta)

    meta["retrieve_vertex_rerank_ms"] = int((time.monotonic() - rr_t0) * 1000)

    order_changed = _order_signature(hits, top_k) != _order_signature(ranked, top_k)
    meta["rerank_order_changed"] = order_changed
    if order_changed:
        log.info(
            "rag_rerank_order_changed top_k=%s dense_first=%s rerank_first=%s",
            top_k,
            (hits[0].get("source_doc"), hits[0].get("section")) if hits else None,
            (ranked[0].get("source_doc"), ranked[0].get("section")) if ranked else None,
        )
    meta["retrieval_returned_count"] = len(ranked)
    return _finalize_return(ranked, meta)
