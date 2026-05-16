"""Normalize retrieval hits into API/UI source card rows."""

from __future__ import annotations

from typing import Any


def compact_sources_from_hits(retrieval_hits: list[Any]) -> list[dict[str, Any]]:
    """Map retrieve_context-style dict hits to trimmed JSON-safe cards."""
    out: list[dict[str, Any]] = []
    for h in retrieval_hits:
        if not isinstance(h, dict):
            continue
        txt = str(h.get("text") or "")
        out.append(
            {
                "point_id": str(h.get("point_id") or ""),
                "source_doc": str(h.get("source_doc") or ""),
                "section": str(h.get("section") or ""),
                "product": str(h.get("product") or ""),
                "page_number": h.get("page_number"),
                "score": h.get("score"),
                "excerpt": txt[:400],
            }
        )
    return out
