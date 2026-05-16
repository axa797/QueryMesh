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

Scores are automatically uploaded to Langfuse as a named trace when
``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set in the environment.
View them at https://cloud.langfuse.com → Traces, filter by name "ragas-eval".

Persist aggregate + per-row scores to Postgres with ``--persist`` or
``EVAL_PERSIST_DATABASE=1`` (requires ``DATABASE_URL`` and Alembic revision
``005_eval_reports_table``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.golden_loader import GoldenRow, load_golden, validate_golden_counts

log = logging.getLogger(__name__)

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


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _aggregate_from_df(df: Any) -> dict[str, float]:
    """Mean of numeric metric columns for Langfuse scores and DB aggregate_metrics."""
    import pandas as pd

    out: dict[str, float] = {}
    means = df.mean(numeric_only=True)
    for k, v in means.items():
        if pd.isna(v):
            continue
        try:
            out[str(k)] = round(float(v), 4)
        except (TypeError, ValueError):
            continue
    return out


def _json_cell_for_eval_db(raw: Any) -> Any:
    """Normalize RAGAS / pandas cell values for JSONB (arrays must not hit ``pd.isna``)."""
    import numpy as np
    import pandas as pd

    if raw is None:
        return None
    if isinstance(raw, np.ndarray):
        return raw.tolist()
    if isinstance(raw, (list, tuple)):
        return [_json_cell_for_eval_db(x) for x in raw]
    if isinstance(raw, (bool, np.bool_)):
        return bool(raw)
    if isinstance(raw, (int, np.integer)):
        return int(raw)
    if isinstance(raw, (float, np.floating)):
        if pd.isna(raw):
            return None
        return round(float(raw), 4)
    try:
        if pd.api.types.is_scalar(raw):
            na = pd.isna(raw)
            if bool(np.asarray(na).any()):
                return None
    except (TypeError, ValueError):
        pass
    return str(raw)


def _per_row_records_for_db(df: Any, retrieval_rows: list) -> list[dict[str, Any]]:
    """JSON-serializable per-sample rows keyed by RAGAS column + golden metadata."""
    out: list[dict[str, Any]] = []
    for row_obj, (_, ser) in zip(retrieval_rows, df.iterrows()):
        rec: dict[str, Any] = {
            "golden_id": str(getattr(row_obj, "id", "")),
            "category": str(getattr(row_obj, "category", "")),
            "question_preview": str(getattr(row_obj, "question", ""))[:300],
        }
        for col, raw in ser.items():
            key = str(col)
            rec[key] = _json_cell_for_eval_db(raw)
        out.append(rec)
    return out


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


def _upload_to_langfuse(
    df: Any,
    agg: dict[str, float],
    *,
    n_samples: int,
    mode: str,
    retrieval_rows: list,
    judge_model: str,
    output_model: str,
    embedding_model: str,
    rerank_enabled: bool,
) -> str | None:
    """Upload RAGAS scores to Langfuse: one parent evaluator trace with per-sample child spans.

    Parent trace carries full pipeline config in metadata and aggregate scores as Langfuse
    score objects. Each evaluated row becomes a child evaluator span with per-row metric
    scores and the answer preview, so you can see exactly which questions regressed.

    Requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment (or
    LANGFUSE_HOST for self-hosted). Returns the parent trace id when upload succeeds.

    View at: Langfuse → Traces, filter name = "ragas-eval".
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        print("Langfuse upload skipped (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set).")
        return None

    trace_id: str | None = None
    try:
        import numpy as np
        from langfuse import Langfuse

        # Service name shows in resourceAttributes instead of "unknown_service".
        os.environ.setdefault("OTEL_SERVICE_NAME", "querymesh-evals")

        lf = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=os.environ.get("LANGFUSE_HOST") or None,
        )

        with lf.start_as_current_observation(
            name="ragas-eval",
            as_type="evaluator",
            metadata={
                "output_model": output_model,
                "judge_model": judge_model,
                "embedding_model": embedding_model,
                "rerank_enabled": rerank_enabled,
                "corpus_tag": "next26",
                "google_cloud_project": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                "n_questions_total": 30,
                "n_questions_evaluated": n_samples,
                "mode": mode,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            },
            output=agg,
        ):
            trace_id = lf.get_current_trace_id()

            # Aggregate scores visible as colored pills in the trace header.
            for metric_name, value in agg.items():
                lf.create_score(name=metric_name, value=value, trace_id=trace_id)

            # Per-sample child spans — one per evaluated row.
            for row, (_, sample_scores) in zip(retrieval_rows, df.iterrows()):
                per_row: dict[str, float] = {}
                for k, raw in sample_scores.items():
                    if isinstance(raw, (float, np.floating)):
                        per_row[str(k)] = round(float(raw), 4)
                answer_preview = getattr(row, "model_answer", getattr(row, "reference_answer", ""))
                with lf.start_as_current_observation(
                    name=row.id,
                    as_type="evaluator",
                    input=row.question,
                    output=per_row,
                    metadata={
                        "category": row.category,
                        "n_contexts": len(getattr(row, "contexts", [])),
                        "answer_preview": str(answer_preview)[:300],
                    },
                ):
                    row_trace_id = lf.get_current_trace_id()
                    for metric_name, value in per_row.items():
                        lf.create_score(
                            name=metric_name,
                            value=value,
                            trace_id=row_trace_id,
                        )

        lf.flush()
        ui_url = lf.get_trace_url(trace_id=trace_id) if trace_id else None
        if trace_id:
            print(f"Scores uploaded to Langfuse — trace: {trace_id}")
            if ui_url:
                print(f"View at: {ui_url}")
            else:
                log.warning(
                    "Langfuse get_trace_url() returned empty (check credentials); "
                    "eval dashboard needs NEXT_PUBLIC_LANGFUSE_PROJECT_ID for legacy links.",
                )
        # Persist canonical UI URL (/project/<id>/traces/...) — not `{host}/traces/{id}`.
        return ui_url or trace_id
    except Exception:
        log.exception("Langfuse upload failed (non-fatal)")
        return None


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
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist metrics to Postgres (Alembic 005_eval_reports_table; needs DATABASE_URL).",
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

    df = result.to_pandas()
    agg = _aggregate_from_df(df)
    lf_trace_id = _upload_to_langfuse(
        df,
        agg,
        n_samples=len(ds),
        mode=mode,
        retrieval_rows=retrieval,
        judge_model=model_name,
        output_model=model_name,
        embedding_model="text-embedding-005",
        rerank_enabled=os.environ.get("RAG_VERTEX_RERANK", "false").lower() == "true",
    )

    persist_db = bool(args.persist or _env_truthy("EVAL_PERSIST_DATABASE"))
    if persist_db:
        db_url = (os.environ.get("DATABASE_URL") or "").strip()
        if not db_url:
            print("Eval DB persist skipped (DATABASE_URL unset).", file=sys.stderr)
        else:
            per_rows = _per_row_records_for_db(df, retrieval)
            trigger_src = (os.environ.get("EVAL_TRIGGER") or "manual").strip()[:64] or "manual"
            git_sha = (os.environ.get("GITHUB_SHA") or os.environ.get("GIT_COMMIT") or "").strip()

            async def _insert() -> None:
                from memory.eval_report_store import insert_eval_report

                await insert_eval_report(
                    mode=mode,
                    n_samples=len(ds),
                    aggregate_metrics=agg,
                    per_row_metrics=per_rows,
                    judge_model=model_name,
                    embedding_model="text-embedding-005",
                    langfuse_trace_id=lf_trace_id,
                    trigger=trigger_src,
                    git_commit=git_sha or None,
                )

            try:
                asyncio.run(_insert())
                print("Eval report persisted to eval_reports table.")
            except Exception:
                log.exception("Eval DB persist failed (non-fatal)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
