"""DeepEval metrics over golden retrieval samples (spec §10).

When ``evals/harvested_dataset.json`` exists (produced by ``evals/harvest.py``), uses the
real model answer and live retrieval contexts rather than the static reference answer.

Run manually / nightly (slow, LLM-costly)::

    uv sync --group eval
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval pytest evals/test_deepeval_suite.py -v

For meaningful scores, harvest first::

    PYTHONPATH=. uv run python evals/harvest.py
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval pytest evals/test_deepeval_suite.py -v

PR pytest excludes ``eval``-marked tests via ``pyproject.toml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evals.golden_loader import load_golden, validate_golden_counts

pytestmark = pytest.mark.eval

_HARVESTED_PATH = Path(__file__).resolve().parent / "harvested_dataset.json"


def _load_best_retrieval_row():
    """Return (question, actual_output, contexts, reference_answer) preferring harvested data."""
    if _HARVESTED_PATH.exists():
        from evals.ragas_eval import load_harvested

        rows = load_harvested()
        for r in rows:
            if r.category == "retrieval" and r.contexts:
                return r.question, r.model_answer, r.contexts, r.reference_answer
        # Fall through if no harvested retrieval rows have contexts.

    # Fallback: static golden data (smoke-test; scores against reference_answer).
    rows = load_golden()
    validate_golden_counts(rows)
    for r in rows:
        if r.category == "retrieval" and r.contexts:
            return r.question, r.reference_answer, r.contexts, r.reference_answer
    return None


@pytest.fixture(scope="module")
def best_retrieval_sample():
    result = _load_best_retrieval_row()
    if result is None:
        pytest.skip("No retrieval row with contexts found in golden or harvested dataset")
    return result


def test_faithfulness_on_retrieval_sample(best_retrieval_sample):
    if not os.environ.get("RUN_EVAL"):
        pytest.skip("RUN_EVAL not set (deepeval calls a judge LLM)")
    pytest.importorskip("deepeval")
    from deepeval import assert_test
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    question, actual_output, contexts, _ = best_retrieval_sample
    source = "harvested" if _HARVESTED_PATH.exists() else "golden (static)"
    print(f"\nUsing {source} data for DeepEval faithfulness test")

    case = LLMTestCase(
        input=question,
        actual_output=actual_output,
        retrieval_context=contexts,
    )
    assert_test(case, [FaithfulnessMetric()])
