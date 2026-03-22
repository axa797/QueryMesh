"""CLI: embed chunks and upsert into Qdrant collection ``gcp_docs`` (spec §9, §15.8)."""

from __future__ import annotations

import argparse
import logging
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ingestion.chunker import TextChunk, chunk_documents
from ingestion.embeddings import embed_in_batches
from ingestion.loader import load_source_dir

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_NAMESPACE_UUID = uuid.uuid5(uuid.NAMESPACE_URL, "querymesh/ingest/point-id")


def _point_id(chunk: TextChunk, ordinal: int) -> str:
    h = f"{chunk.source_doc}|{ordinal}|{chunk.text[:200]}"
    return str(uuid.uuid5(_NAMESPACE_UUID, h))


def ensure_collection(client: QdrantClient, name: str, dim: int, recreate: bool) -> None:
    if recreate:
        log.info("Recreating Qdrant collection %s (dim=%s)", name, dim)
        client.recreate_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        return
    if client.collection_exists(collection_name=name):
        log.info("Using existing collection %s", name)
        return
    log.info("Creating Qdrant collection %s (dim=%s)", name, dim)
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )


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
) -> int:
    raw_docs = load_source_dir(source)
    if not raw_docs:
        log.error("No documents loaded from %s", source)
        return 1
    chunks = chunk_documents(raw_docs)
    if not chunks:
        log.error("No chunks produced from %s", source)
        return 1

    texts = [c.text for c in chunks]
    log.info("Embedding %s chunk(s)…", len(texts))
    vectors = embed_in_batches(
        texts,
        project=project,
        location=location,
        model_id=model_id,
        for_query=False,
    )
    if len(vectors) != len(chunks):
        log.error("Embedding count mismatch: %s vs %s", len(vectors), len(chunks))
        return 1
    dim = len(vectors[0])

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    try:
        ensure_collection(client, collection, dim, recreate)
        points = [
            PointStruct(
                id=_point_id(chunk, i),
                vector=vectors[i],
                payload={
                    "text": chunk.text,
                    "source_doc": chunk.source_doc,
                    "section": chunk.section,
                    "product": chunk.product,
                    "page_number": chunk.page_number,
                },
            )
            for i, chunk in enumerate(chunks)
        ]
        client.upload_points(collection_name=collection, points=points, batch_size=64)
        log.info("Upserted %s point(s) into %s", len(points), collection)
    finally:
        client.close()
    return 0


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
    p.add_argument("--embedding-model", default="text-embedding-004")
    p.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Drop and recreate the Qdrant collection.",
    )
    args = p.parse_args()
    raise SystemExit(
        run_index(
            source=args.source.resolve(),
            qdrant_url=args.qdrant_url,
            qdrant_api_key=args.qdrant_api_key,
            collection=args.collection,
            project=args.google_cloud_project,
            location=args.google_cloud_location,
            model_id=args.embedding_model,
            recreate=args.recreate_collection,
        )
    )


if __name__ == "__main__":
    main()
