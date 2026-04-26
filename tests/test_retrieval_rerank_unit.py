"""Vertex semantic rerank (Discovery Engine) — unit tests with mocked client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from tools import retrieval_tool


@pytest.fixture
def three_hits() -> list[dict]:
    return [
        {
            "text": f"doc{i}",
            "section": f"s{i}",
            "source_doc": "a.pdf",
            "product": "x",
            "page_number": i,
            "score": 0.9 - i * 0.01,
        }
        for i in range(3)
    ]


def test_vertex_rerank_reorders_by_rank_api(three_hits: list[dict]) -> None:
    class FakeRecord:
        __slots__ = ("id", "score")

        def __init__(self, id: str, score: float) -> None:
            self.id = id
            self.score = score

    class FakeResponse:
        __slots__ = ("records",)

        def __init__(self) -> None:
            self.records = [
                FakeRecord("2", 0.99),
                FakeRecord("0", 0.5),
                FakeRecord("1", 0.3),
            ]

    fake_client = MagicMock()
    fake_client.ranking_config_path = MagicMock(
        return_value="projects/p/locations/global/rankingConfigs/default_ranking_config"
    )
    fake_client.rank = MagicMock(return_value=FakeResponse())

    with patch("google.cloud.discoveryengine_v1.RankServiceClient", return_value=fake_client):
        out = retrieval_tool._apply_vertex_rerank(
            "what is Gemini",
            three_hits,
            project="myproj",
            top_k=2,
            model="semantic-ranker-fast-004",
        )

    assert len(out) == 2
    assert out[0]["text"] == "doc2"
    assert out[1]["text"] == "doc0"
    assert out[0]["rerank_score"] == 0.99
    fake_client.rank.assert_called_once()


def test_vertex_rerank_api_error_returns_dense_trim(three_hits: list[dict]) -> None:
    fake_client = MagicMock()
    fake_client.ranking_config_path = MagicMock(return_value="path")
    fake_client.rank = MagicMock(side_effect=RuntimeError("rank api unavailable"))

    with patch("google.cloud.discoveryengine_v1.RankServiceClient", return_value=fake_client):
        out = retrieval_tool._apply_vertex_rerank("q", three_hits, project="p", top_k=2, model="m")

    assert out == three_hits[:2]


def test_vertex_rerank_preflight_few_candidates() -> None:
    skip = retrieval_tool._vertex_rerank_preflight_skip_reason
    assert skip([], min_dense_score=None) == "few_candidates"
    one = [{"text": "a", "source_doc": "x", "score": 0.9}]
    assert skip(one, min_dense_score=None) == "few_candidates"


def test_vertex_rerank_preflight_low_dense_score(three_hits: list[dict]) -> None:
    skip = retrieval_tool._vertex_rerank_preflight_skip_reason
    assert skip(three_hits, min_dense_score=0.95) == "low_dense_score"
    assert skip(three_hits, min_dense_score=0.80) is None


def test_vertex_rerank_preflight_no_min_uses_pool_size_only(three_hits: list[dict]) -> None:
    skip = retrieval_tool._vertex_rerank_preflight_skip_reason
    assert skip(three_hits, min_dense_score=None) is None


def test_vertex_rerank_preflight_missing_top_score_allows_rerank() -> None:
    skip = retrieval_tool._vertex_rerank_preflight_skip_reason
    hits = [{"text": "a", "source_doc": "1"}, {"text": "b", "source_doc": "2", "score": 0.1}]
    assert skip(hits, min_dense_score=0.99) is None


def test_order_signature_detects_reorder(three_hits: list[dict]) -> None:
    sig = retrieval_tool._order_signature
    swapped = [three_hits[2], three_hits[0]]
    assert sig(three_hits, 2) != sig(swapped, 2)
    assert sig(three_hits, 2) == sig(three_hits, 2)
