"""Chunker unit tests."""

from __future__ import annotations

from ingestion.chunker import TextChunk, chunk_documents
from llama_index.core import Document


def test_markdown_chunks_with_section_metadata() -> None:
    docs = [
        Document(
            text="# Title\n\nFirst paragraph.\n\n## Sub\n\nSecond.",
            metadata={"file_path": "doc.md"},
        )
    ]
    chunks = chunk_documents(docs)
    assert len(chunks) >= 1
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert all(c.source_doc == "doc.md" for c in chunks)


def test_pdf_like_uses_token_splitter() -> None:
    docs = [
        Document(
            text="word " * 800,
            metadata={"file_path": "x.pdf", "file_type": "application/pdf"},
        )
    ]
    chunks = chunk_documents(docs)
    assert len(chunks) >= 2
