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


def chunk_documents(docs: list[Document]) -> list[TextChunk]:
    """Split documents into chunks with metadata (spec §9)."""
    if not docs:
        return []

    all_markdown = all(
        str((d.metadata or {}).get("file_type", "")).lower() == ".md"
        or str((d.metadata or {}).get("file_path", "")).lower().endswith(".md")
        for d in docs
    )

    used_markdown = False
    try:
        if all_markdown:
            nodes, used_markdown = _nodes_from_markdown(docs)
        else:
            nodes, used_markdown = _nodes_from_token_split(docs, warn_fallback=True)
    except Exception:
        log.warning("Markdown chunking failed; falling back to token splitter", exc_info=True)
        nodes, used_markdown = _nodes_from_token_split(docs, warn_fallback=not all_markdown)

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

    log.info(
        "Chunked into %s segment(s); section_style_markdown=%s",
        len(chunks),
        used_markdown,
    )
    return chunks
