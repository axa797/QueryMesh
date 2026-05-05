"""Harvest real retrieval contexts and RAG model answers for RAGAS evaluation.

Calls the retrieval tool and RAG agent directly — no API server needed. Writes
``evals/harvested_dataset.json`` with ``contexts`` populated from live Qdrant retrieval and
``model_answer`` from the RAG agent's Vertex Gemini response.

Prerequisites
-------------
- Qdrant running and accessible (``QDRANT_URL``; default ``http://localhost:6333``).
- Next '26 corpus indexed (run ``scripts/fetch_next26_corpus.py`` then ``POST /ingest``).
- ``GOOGLE_CLOUD_PROJECT`` set and ADC active (``gcloud auth application-default login``).
- ``DATABASE_URL``, ``API_KEY_PEPPER``, ``REDIS_URL`` in ``.env`` or environment (values are
  read by the Settings loader but NOT used for connections in this script).

Run from the repo root::

    PYTHONPATH=. uv run python evals/harvest.py

Optional flags::

    --limit N          Process only the first N retrieval rows (default: all)
    --dataset PATH     Override golden_dataset.json path
    --out PATH         Override output path (default: evals/harvested_dataset.json)
    --categories       Comma-separated list of categories to harvest (default: all)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Set minimal required env vars before importing any app module so that
# pydantic-settings can construct Settings without a live DB or Redis.
# Values from .env file will override these if present (pydantic-settings
# honours .env when it exists at the project root).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://harvest:harvest@localhost/harvest")
os.environ.setdefault("API_KEY_PEPPER", "harvest-dummy-pepper")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Disable Vertex rerank during harvest so we only need core Qdrant + embedding.
os.environ.setdefault("RAG_VERTEX_RERANK", "false")

from agents.rag_agent import run_rag_structured  # noqa: E402
from tools.retrieval_tool import retrieve_context  # noqa: E402

from evals.golden_loader import (  # noqa: E402
    GoldenRow,
    load_golden,
    validate_golden_counts,
)

log = logging.getLogger("evals.harvest")

_HARVESTED_PATH = Path(__file__).resolve().parent / "harvested_dataset.json"


async def _harvest_row(row: GoldenRow) -> dict:
    """Return a dict ready for harvested_dataset.json for one golden row."""
    hits, _meta = await retrieve_context(row.question)
    contexts = [h["text"] for h in hits if h.get("text")]

    model_answer: str
    if hits:
        rag = await run_rag_structured(row.question, hits)
        model_answer = rag.get("answer") or row.reference_answer
    else:
        # No corpus hits — fall back to the gold reference so RAGAS can still run.
        log.warning("No retrieval hits for %s — using reference_answer as fallback", row.id)
        model_answer = row.reference_answer

    return {
        "id": row.id,
        "category": row.category,
        "question": row.question,
        "reference_answer": row.reference_answer,
        "contexts": contexts,
        "model_answer": model_answer,
    }


async def harvest(
    rows: list[GoldenRow],
    *,
    categories: set[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Harvest all rows (or a filtered subset) and return the harvested list."""
    target = [r for r in rows if categories is None or r.category in categories]
    if limit is not None:
        # Apply limit per category so RAGAS still has a balanced slice.
        from collections import defaultdict

        by_cat: dict[str, list[GoldenRow]] = defaultdict(list)
        for r in target:
            by_cat[r.category].append(r)
        target = []
        for cat_rows in by_cat.values():
            target.extend(cat_rows[:limit])

    harvested: list[dict] = []
    for i, row in enumerate(target, 1):
        print(f"[{i}/{len(target)}] {row.id} ({row.category}) — retrieving ...", flush=True)
        try:
            result = await _harvest_row(row)
            n_ctx = len(result["contexts"])
            ans_preview = (result["model_answer"] or "")[:80].replace("\n", " ")
            print(f"         contexts={n_ctx}  answer={ans_preview!r}")
            harvested.append(result)
        except Exception:
            log.exception("Failed to harvest row %s — skipping", row.id)

    return harvested


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Override path to golden_dataset.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_HARVESTED_PATH,
        help="Output path (default: evals/harvested_dataset.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max rows per category to harvest (default: all)",
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="Comma-separated categories to harvest, e.g. retrieval,code_generation (default: all)",
    )
    args = parser.parse_args(argv)

    rows = load_golden(args.dataset)
    try:
        validate_golden_counts(rows)
    except ValueError as e:
        print(f"WARNING: golden validation: {e}", file=sys.stderr)

    cats: set[str] | None = None
    if args.categories:
        cats = {c.strip() for c in args.categories.split(",") if c.strip()}

    print(f"Harvesting {len(rows)} rows (categories={cats or 'all'}, limit={args.limit}) ...")
    print("Prerequisites: Qdrant up + corpus indexed + GOOGLE_CLOUD_PROJECT set + ADC active\n")

    harvested = asyncio.run(harvest(rows, categories=cats, limit=args.limit))

    args.out.write_text(
        json.dumps(harvested, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    n_with_ctx = sum(1 for r in harvested if r.get("contexts"))
    print(
        f"\nWrote {len(harvested)} rows to {args.out}  ({n_with_ctx} with real retrieval contexts)"
    )
    if n_with_ctx == 0:
        print(
            "\nWARNING: No rows have retrieval contexts. Check that:\n"
            "  1. Qdrant is running (docker compose up)\n"
            '  2. The corpus is indexed (POST /ingest {"source":"gcp_docs"})\n'
            "  3. GOOGLE_CLOUD_PROJECT is set and ADC is active"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
