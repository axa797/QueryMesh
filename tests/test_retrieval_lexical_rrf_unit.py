"""Lexical RRF helper (prefetch reorder, no Qdrant calls)."""

from __future__ import annotations

from tools import retrieval_tool


def test_reciprocal_rank_fusion_keeps_all_candidates() -> None:
    fused = retrieval_tool._reciprocal_rank_fusion(
        [[0, 1, 2], [2, 0, 1]],
        k=60,
    )
    assert fused == [0, 2, 1]


def test_apply_lexical_rrf_reorders_when_signals_diverge() -> None:
    hits = [
        {
            "text": "The model training uses large batch sizes for TPUs.",
            "source_doc": "a.pdf",
            "section": "s1",
        },
        {
            "text": "Coffee break policy for employees.",
            "source_doc": "b.pdf",
            "section": "s2",
        },
        {
            "text": "TPU 8t batch size and interconnect details for training.",
            "source_doc": "c.pdf",
            "section": "s3",
        },
    ]
    terms = retrieval_tool._lex_query_terms("TPU training batch size")
    merged = retrieval_tool._apply_lexical_rrf(hits, terms)
    assert merged[0]["source_doc"] != "b.pdf"
