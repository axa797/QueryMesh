"""Load PDFs (and other files) with LlamaIndex SimpleDirectoryReader (spec §9)."""

from __future__ import annotations

import logging
from pathlib import Path

from llama_index.core import SimpleDirectoryReader

log = logging.getLogger(__name__)


def load_source_dir(source: Path) -> list:
    """Load documents from ``source`` (directory, recursive)."""
    if not source.is_dir():
        raise FileNotFoundError(f"Source is not a directory: {source}")
    reader = SimpleDirectoryReader(
        input_dir=str(source),
        recursive=True,
        filename_as_id=True,
    )
    docs = reader.load_data(show_progress=True)
    log.info("Loaded %s document(s) from %s", len(docs), source)
    return docs
