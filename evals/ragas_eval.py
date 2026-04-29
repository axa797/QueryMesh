"""RAGAS runner over retrieval rows in the golden set (spec §10).

Dry-run (default): validates golden JSON — **no** ``ragas`` import.

Full run: set ``RUN_EVAL=1``, ``GOOGLE_CLOUD_PROJECT``, and ADC; install eval deps::

    uv sync --group eval
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --limit 5

Use ``--harvested`` to evaluate against **real** pipeline output (recommended):

    # 1. Index the corpus, then harvest live retrieval + model answers:
    PYTHONPATH=. uv run python evals/harvest.py

    # 2. Run RAGAS with the harvested file:
    RUN_EVAL=1 PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --harvested --limit 10

Without ``--harvested`` the runner uses the static ``contexts`` and ``reference_answer``
baked into golden_dataset.json — useful for CI smoke checks but not a real quality signal.

Uses Vertex (Gemini) via LangChain for RAGAS judge LLM.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.golden_loader import GoldenRow, load_golden, validate_golden_counts

_HARVESTED_PATH = Path(__file__).resolve().parent / "harvested_dataset.json"


@dataclass(frozen=True)
class HarvestedRow:
    id: str
    category: str
    question: str
    reference_answer: str
    contexts: list[str]
    model_answer: str


def load_harvested(path: Path | None = None) -> list[HarvestedRow]:
    p = path or _HARVESTED_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Harvested dataset not found at {p}. "
            "Run `PYTHONPATH=. uv run python evals/harvest.py` first."
        )
    raw = json.loads(p.read_text(encoding="utf-8"))
    rows: list[HarvestedRow] = []
    for item in raw:
        rows.append(
            HarvestedRow(
                id=str(item.get("id", "")),
                category=str(item.get("category", "")),
                question=str(item.get("question", "")),
                reference_answer=str(item.get("reference_answer", "")),
                contexts=[str(c) for c in (item.get("contexts") or [])],
                model_answer=str(item.get("model_answer") or item.get("reference_answer", "")),
            )
        )
    return rows


def _rows_to_ragas_dataset_golden(rows: list[GoldenRow]):
    """Build RAGAS dataset from static golden rows (smoke-test mode, no live retrieval)."""
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


def _rows_to_ragas_dataset_harvested(rows: list[HarvestedRow]):
    """Build RAGAS dataset from harvested rows (real retrieval + model answers)."""
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

    samples = []
    for r in rows:
        if not r.contexts:
            continue
        samples.append(
            SingleTurnSample(
                user_input=r.question,
                retrieved_contexts=r.contexts,
                response=r.model_answer,
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
        help="Override path to golden_dataset.json (ignored when --harvested is set)",
    )
    parser.add_argument(
        "--harvested",
        action="store_true",
        help=(
            "Use evals/harvested_dataset.json (real retrieval contexts + model answers). "
            "Run `evals/harvest.py` first. This is the recommended mode for meaningful scores."
        ),
    )
    parser.add_argument(
        "--harvested-path",
        type=Path,
        default=None,
        help="Override path to harvested_dataset.json (default: evals/harvested_dataset.json)",
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

    if args.harvested:
        try:
            harvested_rows = load_harvested(args.harvested_path)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        retrieval = [r for r in harvested_rows if r.category == "retrieval"][: args.limit]
        n_ctx = sum(1 for r in retrieval if r.contexts)
        print(
            f"Harvested: {len(harvested_rows)} rows; "
            f"retrieval slice: {len(retrieval)}; with real contexts: {n_ctx}"
        )
        mode = "harvested (real pipeline output)"
    else:
        rows = load_golden(args.dataset)
        validate_golden_counts(rows)
        retrieval = [r for r in rows if r.category == "retrieval"][: args.limit]  # type: ignore[assignment]
        n_ctx = sum(1 for r in retrieval if r.contexts)
        print(
            f"Golden: {len(rows)} rows; retrieval slice: {len(retrieval)}; with contexts: {n_ctx}"
        )
        mode = "golden (static contexts — smoke-test only)"

    print(f"Mode: {mode}")

    if args.dry_run or not os.environ.get("RUN_EVAL"):
        print(
            "Skipping RAGAS judge (set RUN_EVAL=1 and omit --dry-run; needs: uv sync --group eval)."
        )
        return 0

    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        print("GOOGLE_CLOUD_PROJECT required for RAGAS judge.", file=sys.stderr)
        return 2

    try:
        from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings
        from ragas import evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as e:
        print(f"Import error (install with: uv sync --group eval): {e}", file=sys.stderr)
        return 3

    if args.harvested:
        ds = _rows_to_ragas_dataset_harvested(retrieval)  # type: ignore[arg-type]
    else:
        ds = _rows_to_ragas_dataset_golden(retrieval)  # type: ignore[arg-type]

    if len(ds) == 0:
        print("No samples with contexts to evaluate.", file=sys.stderr)
        return 4

    location = (os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1").strip()
    model_name = os.environ.get("VERTEX_LLM_MODEL") or "gemini-2.5-flash"
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lc_llm = ChatVertexAI(
            model_name=model_name,
            project=project,
            location=location,
            temperature=0,
        )
        lc_emb = VertexAIEmbeddings(
            model_name="text-embedding-005",
            project=project,
            location=location,
        )
    ragas_llm = LangchainLLMWrapper(lc_llm)
    ragas_emb = LangchainEmbeddingsWrapper(lc_emb)

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    for m in metrics:
        m.llm = ragas_llm
    answer_relevancy.embeddings = ragas_emb

    print(f"Running RAGAS on {len(ds)} samples (LLM judge calls) ...")
    result = evaluate(dataset=ds, metrics=metrics, embeddings=ragas_emb, show_progress=True)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
