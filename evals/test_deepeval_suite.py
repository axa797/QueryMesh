"""DeepEval metrics over golden retrieval samples (spec §10).

Run manually / nightly (slow, LLM-costly)::

    uv sync --group eval
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval pytest evals/test_deepeval_suite.py -v

PR pytest excludes ``eval``-marked tests via ``pyproject.toml``.
"""

from __future__ import annotations

import os

import pytest

from evals.golden_loader import load_golden, validate_golden_counts

pytestmark = pytest.mark.eval


@pytest.fixture(scope="module")
def first_retrieval_row():
    rows = load_golden()
    validate_golden_counts(rows)
    for r in rows:
        if r.category == "retrieval" and r.contexts:
            return r
    pytest.skip("no retrieval row with contexts")


def test_faithfulness_on_golden_sample(first_retrieval_row):
    if not os.environ.get("RUN_EVAL"):
        pytest.skip("RUN_EVAL not set (deepeval calls a judge LLM)")
    pytest.importorskip("deepeval")
    from deepeval import assert_test
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    r = first_retrieval_row
    case = LLMTestCase(
        input=r.question,
        actual_output=r.reference_answer,
        retrieval_context=r.contexts,
    )
    assert_test(case, [FaithfulnessMetric()])
