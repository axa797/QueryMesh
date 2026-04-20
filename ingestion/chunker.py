"""Chunking: section-aware for Markdown, token splitter fallback (spec §9)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, TokenTextSplitter
from llama_index.core.schema import BaseNode

log = logging.getLogger(__name__)

_CHUNK = 512
_OVERLAP = 50
# Vertex text-embedding-* caps inputs (~2048 tokens); oversized Markdown sections must be split.
_MAX_CHUNK_CHARS = 4500


@dataclass(frozen=True)
class TextChunk:
    text: str
    source_doc: str
    section: str
    product: str
    page_number: int | None


def _infer_product(source_doc: str) -> str:
    lower = source_doc.lower()
    for name in (
        "bigquery",
        "gke",
        "kubernetes",
        "storage",
        "cloud-sql",
        "vertex",
        "compute",
    ):
        if name in lower:
            return name
    stem = Path(source_doc).stem
    return stem[:64] if stem else "unknown"


def _nodes_from_markdown(docs: list[Document]) -> tuple[list[BaseNode], bool]:
    parser = MarkdownNodeParser.from_defaults()
    nodes: list[BaseNode] = []
    for doc in docs:
        nodes.extend(parser.get_nodes_from_documents([doc]))
    return nodes, True


def _nodes_from_token_split(
    docs: list[Document], warn_fallback: bool
) -> tuple[list[BaseNode], bool]:
    if warn_fallback:
        log.warning(
            "Using fixed-size TokenTextSplitter (%s tokens, overlap %s); "
            "section-aware Markdown parse not used for these documents (spec §9 fallback).",
            _CHUNK,
            _OVERLAP,
        )
    splitter = TokenTextSplitter(chunk_size=_CHUNK, chunk_overlap=_OVERLAP)
    nodes: list[BaseNode] = []
    for doc in docs:
        nodes.extend(splitter.get_nodes_from_documents([doc]))
    return nodes, False


_PAGE_LABEL_RE = re.compile(r"^(\d+)$")


def _page_from_metadata(meta: dict) -> int | None:
    label = meta.get("page_label")
    if label is None:
        return None
    if isinstance(label, int):
        return label
    m = _PAGE_LABEL_RE.match(str(label).strip())
    return int(m.group(1)) if m else None


def _doc_base_name(meta: dict) -> str:
    for key in ("file_name", "file_path"):
        val = meta.get(key)
        if val:
            return str(Path(str(val)).name)
    return "unknown"


def _section_from_node(node: BaseNode) -> str:
    meta = node.metadata or {}
    if "section_title" in meta:
        return str(meta["section_title"])
    header = meta.get("header_path")
    if header:
        return str(header)
    return ""


def _split_oversized_chunks(chunks: list[TextChunk]) -> list[TextChunk]:
    """Keep chunks under model input limits (see Vertex text embedding token caps)."""
    if not chunks:
        return []
    splitter = TokenTextSplitter(chunk_size=_CHUNK, chunk_overlap=_OVERLAP)
    out: list[TextChunk] = []
    for c in chunks:
        if len(c.text) <= _MAX_CHUNK_CHARS:
            out.append(c)
            continue
        sub_docs = [Document(text=c.text)]
        for node in splitter.get_nodes_from_documents(sub_docs):
            piece = (node.get_content(metadata_mode="none") or "").strip()
            if piece:
                out.append(
                    TextChunk(
                        text=piece,
                        source_doc=c.source_doc,
                        section=c.section,
                        product=c.product,
                        page_number=c.page_number,
                    )
                )
    return out


def _is_markdown_document(doc: Document) -> bool:
    """Treat .md / markdown MIME as Markdown; everything else uses the token splitter (e.g. PDF)."""
    meta = doc.metadata or {}
    ft = str(meta.get("file_type", "")).lower()
    if ft in (".md", ".markdown", "text/markdown"):
        return True
    fp = str(meta.get("file_path", "")).lower()
    return fp.endswith(".md") or fp.endswith(".markdown")


def chunk_documents(docs: list[Document]) -> list[TextChunk]:
    """Split documents into chunks with metadata (spec §9)."""
    if not docs:
        return []

    md_docs = [d for d in docs if _is_markdown_document(d)]
    other_docs = [d for d in docs if not _is_markdown_document(d)]

    nodes: list[BaseNode] = []
    section_style_markdown = False
    try:
        if md_docs:
            md_nodes, section_style_markdown = _nodes_from_markdown(md_docs)
            nodes.extend(md_nodes)
        if other_docs:
            other_nodes, _ = _nodes_from_token_split(other_docs, warn_fallback=False)
            nodes.extend(other_nodes)
    except Exception:
        log.warning(
            "Chunking failed; falling back to token splitter for all %s document(s)",
            len(docs),
            exc_info=True,
        )
        nodes, _ = _nodes_from_token_split(docs, warn_fallback=True)
        section_style_markdown = False

    chunks: list[TextChunk] = []
    for node in nodes:
        text = (node.get_content(metadata_mode="none") or "").strip()
        if not text:
            continue
        meta = node.metadata or {}
        source = _doc_base_name(meta)
        section = _section_from_node(node)
        product = str(meta.get("product") or _infer_product(source))
        page = _page_from_metadata(meta)
        chunks.append(
            TextChunk(
                text=text,
                source_doc=source,
                section=section,
                product=product,
                page_number=page,
            )
        )

    chunks = _split_oversized_chunks(chunks)

    log.info(
        "Chunked into %s segment(s); md_files=%s split_files=%s section_md=%s",
        len(chunks),
        len(md_docs),
        len(other_docs),
        section_style_markdown,
    )
    return chunks
