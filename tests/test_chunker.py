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


def test_mixed_md_and_pdf_uses_per_file_chunking() -> None:
    """Markdown keeps section-aware nodes; PDFs use token splitter only."""
    docs = [
        Document(
            text="# Overview\n\nIntro.\n\n## Detail\n\nBody.",
            metadata={"file_path": "guide.md", "file_type": ".md"},
        ),
        Document(
            text="x " * 400,
            metadata={"file_path": "blob.pdf", "file_type": "application/pdf"},
        ),
    ]
    chunks = chunk_documents(docs)
    md_chunks = [c for c in chunks if c.source_doc == "guide.md"]
    pdf_chunks = [c for c in chunks if c.source_doc == "blob.pdf"]
    assert md_chunks
    assert pdf_chunks
    assert any("Overview" in (c.section or "") for c in md_chunks)
    assert any("Body" in c.text for c in md_chunks)
