"""RAGAS runner over retrieval rows in the golden set (spec §10).

Dry-run (default): validates golden JSON — **no** ``ragas`` import.

Full run: set ``RUN_EVAL=1``, ``GOOGLE_CLOUD_PROJECT``, and ADC; install eval deps::

    uv sync --group eval
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --limit 5

Uses Vertex (Gemini) via LangChain for RAGAS judge LLM.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from evals.golden_loader import GoldenRow, load_golden, validate_golden_counts


def _rows_to_ragas_dataset(rows: list[GoldenRow]):
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

    samples = []
    for r in rows:
        if not r.contexts:
            continue
        samples.append(
            SingleTurnSample(
                user_input=r.question,
                retrieved_contexts=r.contexts,
                response=r.reference_answer,
                reference=r.reference_answer,
            ),
        )
    return EvaluationDataset(samples=samples)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAGAS eval on golden retrieval contexts")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Override path to golden_dataset.json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max retrieval rows to consider (with contexts)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate golden file; do not import ragas or call judge LLM",
    )
    args = parser.parse_args(argv)

    rows = load_golden(args.dataset)
    validate_golden_counts(rows)
    retrieval = [r for r in rows if r.category == "retrieval"][: args.limit]
    n_ctx = sum(1 for r in retrieval if r.contexts)
    print(f"Golden: {len(rows)} rows; retrieval slice: {len(retrieval)}; with contexts: {n_ctx}")

    if args.dry_run or not os.environ.get("RUN_EVAL"):
        print(
            "Skipping RAGAS judge "
            "(set RUN_EVAL=1 and omit --dry-run; needs: uv sync --group eval).",
        )
        return 0

    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        print("GOOGLE_CLOUD_PROJECT required for RAGAS judge.", file=sys.stderr)
        return 2

    try:
        from langchain_google_vertexai import ChatVertexAI
        from ragas import evaluate
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )
    except ImportError as e:
        print(f"Import error (install with: uv sync --group eval): {e}", file=sys.stderr)
        return 3

    ds = _rows_to_ragas_dataset(retrieval)
    if len(ds) == 0:
        print("No samples with contexts to evaluate.", file=sys.stderr)
        return 4

    location = (os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1").strip()
    lc_llm = ChatVertexAI(
        model_name=(os.environ.get("VERTEX_LLM_MODEL") or "gemini-2.0-flash"),
        project=project,
        location=location,
        temperature=0,
    )
    ragas_llm = LangchainLLMWrapper(lc_llm)
    metrics = [
        Faithfulness(),
        AnswerRelevancy(),
        ContextPrecision(),
        ContextRecall(),
    ]

    print("Running RAGAS (LLM calls)...")
    result = evaluate(dataset=ds, metrics=metrics, llm=ragas_llm, show_progress=True)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
