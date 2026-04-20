"""Vertex AI text embeddings (``text-embedding-005``; batched under request token caps)."""

from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

# Vertex embed API: total input tokens per request ~20k (see INVALID_ARGUMENT from batch too large).
_EST_CHARS_PER_TOKEN = 3
_MAX_REQUEST_TOKENS_BUDGET = 16_000


@lru_cache(maxsize=8)
def _get_text_embedding_model(project: str, location: str, model_id: str):
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    vertexai.init(project=project, location=location)
    return TextEmbeddingModel.from_pretrained(model_id)


def _embed_batch_plain(model, texts: list[str]) -> list[list[float]]:
    return [e.values for e in model.get_embeddings(texts)]


def _embed_batch_with_task(model, texts: list[str], for_query: bool) -> list[list[float]]:
    from vertexai.language_models import TextEmbeddingInput

    task = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"
    inputs = [TextEmbeddingInput(t, task) for t in texts]
    return [e.values for e in model.get_embeddings(inputs)]


def _est_tokens(text: str) -> int:
    """Conservative token estimate for batch budgeting (English-heavy docs)."""
    return max(len(text) // _EST_CHARS_PER_TOKEN, 1)


def embed_texts(
    texts: list[str],
    *,
    project: str,
    location: str,
    model_id: str,
    for_query: bool = False,
) -> list[list[float]]:
    """Embed ``texts`` with optional RETRIEVAL_QUERY / RETRIEVAL_DOCUMENT task types."""
    if not texts:
        return []
    model = _get_text_embedding_model(project, location, model_id)
    try:
        return _embed_batch_with_task(model, texts, for_query)
    except Exception:
        log.debug("TextEmbeddingInput failed; using plain get_embeddings", exc_info=True)
        return _embed_batch_plain(model, texts)


def embed_query_text(
    text: str,
    *,
    project: str,
    location: str,
    model_id: str,
) -> list[float]:
    vecs = embed_texts(
        [text],
        project=project,
        location=location,
        model_id=model_id,
        for_query=True,
    )
    return vecs[0]


def embed_in_batches(
    texts: list[str],
    *,
    project: str,
    location: str,
    model_id: str,
    for_query: bool = False,
) -> list[list[float]]:
    out: list[list[float]] = []
    batch: list[str] = []
    acc = 0
    for t in texts:
        et = _est_tokens(t)
        if batch and acc + et > _MAX_REQUEST_TOKENS_BUDGET:
            out.extend(
                embed_texts(
                    batch,
                    project=project,
                    location=location,
                    model_id=model_id,
                    for_query=for_query,
                )
            )
            batch = []
            acc = 0
        batch.append(t)
        acc += et
    if batch:
        out.extend(
            embed_texts(
                batch,
                project=project,
                location=location,
                model_id=model_id,
                for_query=for_query,
            )
        )
    return out
