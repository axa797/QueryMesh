"""CLI: embed chunks and upsert into Qdrant collection ``gcp_docs`` (spec §9, §15.8)."""

from __future__ import annotations

import argparse
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ingestion.chunker import TextChunk, chunk_documents
from ingestion.embeddings import embed_in_batches
from ingestion.loader import load_source_dir

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_URL, "querymesh/ingest/point-id")


@dataclass(frozen=True)
class RunIndexResult:
    """CLI exit code + number of vectors upserted (for ingestion job store)."""

    exit_code: int
    docs_indexed: int
    message: str = ""


def _point_id(chunk: TextChunk, ordinal: int) -> str:
    h = f"{chunk.source_doc}|{ordinal}|{chunk.text[:200]}"
    return str(uuid.uuid5(_NAMESPACE_UUID, h))


def _qdrant_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"api-key": api_key.strip()}


def _qdrant_rest_ensure_collection(
    base: str,
    collection: str,
    dim: int,
    *,
    recreate: bool,
    api_key: str | None,
    timeout: float,
) -> None:
    """Create collection via Qdrant REST (same transport as ``ping_qdrant`` / curl)."""
    u = base.rstrip("/")
    headers = _qdrant_headers(api_key)
    with httpx.Client(timeout=timeout) as client:
        if recreate:
            log.info("Recreating Qdrant collection %s (dim=%s)", collection, dim)
            r = client.delete(f"{u}/collections/{collection}", headers=headers)
            if r.status_code not in (200, 404):
                r.raise_for_status()
        r = client.get(f"{u}/collections/{collection}", headers=headers)
        if r.status_code == 200:
            log.info("Using existing collection %s", collection)
            return
        if r.status_code != 404:
            r.raise_for_status()
        log.info("Creating Qdrant collection %s (dim=%s)", collection, dim)
        r = client.put(
            f"{u}/collections/{collection}",
            headers=headers,
            json={"vectors": {"size": dim, "distance": "Cosine"}},
        )
        r.raise_for_status()


def _qdrant_rest_upload_points(
    base: str,
    collection: str,
    points: list[dict[str, Any]],
    *,
    api_key: str | None,
    timeout: float,
    batch_size: int = 64,
) -> None:
    u = base.rstrip("/")
    headers = {**_qdrant_headers(api_key), "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            r = client.put(
                f"{u}/collections/{collection}/points?wait=true",
                headers=headers,
                json={"points": batch},
            )
            r.raise_for_status()


def run_index(
    *,
    source: Path,
    qdrant_url: str,
    qdrant_api_key: str | None,
    collection: str,
    project: str,
    location: str,
    model_id: str,
    recreate: bool,
    qdrant_timeout_seconds: int = 60,
) -> RunIndexResult:
    try:
        raw_docs = load_source_dir(source)
    except (FileNotFoundError, OSError) as e:
        log.error("Cannot load source %s: %s", source, e)
        return RunIndexResult(1, 0, str(e))
    if not raw_docs:
        log.error("No documents loaded from %s", source)
        return RunIndexResult(1, 0, "No documents loaded")
    chunks = chunk_documents(raw_docs)
    if not chunks:
        log.error("No chunks produced from %s", source)
        return RunIndexResult(1, 0, "No chunks produced")

    texts = [c.text for c in chunks]
    log.info("Embedding %s chunk(s)…", len(texts))
    try:
        vectors = embed_in_batches(
            texts,
            project=project,
            location=location,
            model_id=model_id,
            for_query=False,
        )
    except Exception as e:
        log.exception("Embedding failed")
        return RunIndexResult(1, 0, str(e))
    if len(vectors) != len(chunks):
        log.error("Embedding count mismatch: %s vs %s", len(vectors), len(chunks))
        return RunIndexResult(1, 0, "Embedding count mismatch")
    dim = len(vectors[0])

    base = (qdrant_url or "").strip().rstrip("/")
    if not base:
        return RunIndexResult(1, 0, "qdrant_url is empty")
    timeout = float(qdrant_timeout_seconds)
    try:
        _qdrant_rest_ensure_collection(
            base,
            collection,
            dim,
            recreate=recreate,
            api_key=qdrant_api_key,
            timeout=timeout,
        )
        points_body = [
            {
                "id": _point_id(chunk, i),
                "vector": vectors[i],
                "payload": {
                    "text": chunk.text,
                    "source_doc": chunk.source_doc,
                    "section": chunk.section,
                    "product": chunk.product,
                    "page_number": chunk.page_number,
                },
            }
            for i, chunk in enumerate(chunks)
        ]
        _qdrant_rest_upload_points(
            base,
            collection,
            points_body,
            api_key=qdrant_api_key,
            timeout=timeout,
            batch_size=64,
        )
        log.info("Upserted %s point(s) into %s", len(points_body), collection)
    except Exception as e:
        log.exception("Qdrant upsert failed")
        return RunIndexResult(1, 0, str(e))
    return RunIndexResult(0, len(chunks), "")


def main() -> None:
    p = argparse.ArgumentParser(description="Ingest PDFs into Qdrant (Vertex embeddings).")
    p.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Directory of source documents (PDF, Markdown, …).",
    )
    p.add_argument("--qdrant-url", default="http://localhost:6333")
    p.add_argument("--qdrant-api-key", default=None)
    p.add_argument("--collection", default="gcp_docs")
    p.add_argument("--google-cloud-project", required=True)
    p.add_argument("--google-cloud-location", default="us-central1")
    p.add_argument("--embedding-model", default="text-embedding-005")
    p.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Drop and recreate the Qdrant collection.",
    )
    p.add_argument(
        "--qdrant-timeout",
        type=int,
        default=60,
        help="REST timeout in seconds for Qdrant API calls (default: 60).",
    )
    args = p.parse_args()
    r = run_index(
        source=args.source.resolve(),
        qdrant_url=args.qdrant_url,
        qdrant_api_key=args.qdrant_api_key,
        collection=args.collection,
        project=args.google_cloud_project,
        location=args.google_cloud_location,
        model_id=args.embedding_model,
        recreate=args.recreate_collection,
        qdrant_timeout_seconds=args.qdrant_timeout,
    )
    raise SystemExit(r.exit_code)


if __name__ == "__main__":
    main()
