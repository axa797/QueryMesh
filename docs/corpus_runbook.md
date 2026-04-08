# Corpus runbook (Phase 2)

Public **GCP documentation PDFs only**. The repo does not ship PDFs: use a local directory, default **`./corpus/gcp_docs`** ([`.env.example`](../.env.example) → `INGESTION_GCP_DOCS_DIR`). The directory is **gitignored** (`corpus/`).

## Target size (spec)

- About **15–20 PDFs**, roughly **500–800 pages** total (Cloud Run, Vertex AI, BigQuery, GKE, Cloud Storage, …).
- Quality over quantity: keep headings and export quality high so section-aware chunking works.

## Layout

```text
corpus/
└── gcp_docs/
    ├── cloud-run-overview.pdf
    ├── vertex-ai-overview.pdf
    └── ...
```

Set:

```bash
export INGESTION_GCP_DOCS_DIR=./corpus/gcp_docs
```

## Prerequisites

- **Docker:** [infra/docker-compose.yml](infra/docker-compose.yml) — Postgres, Redis, Qdrant up.
- **ADC:** `gcloud auth application-default login` — Vertex embeddings for ingestion ([AGENTS.md](../AGENTS.md)).
- **`GOOGLE_CLOUD_PROJECT`** set (and Qdrant reachable via `QDRANT_URL` / local default).
- **Alembic:** `uv run alembic upgrade head` (includes `ingestion_jobs` table).

## Refresh workflow

1. Add or replace PDFs under `corpus/gcp_docs/` (same filename + updated bytes is fine).
2. **Optional full re-embed:** set `INGESTION_RECREATE_COLLECTION=true` **once** if you want to drop and recreate the Qdrant collection. Otherwise the indexer **upserts** with deterministic point IDs (re-run overwrites same logical chunks).
3. Start the API with `.env` loaded.
4. Start a job:

   ```bash
   curl -sS -X POST "$BASE_URL/ingest" \
     -H "Authorization: Bearer $API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"source":"gcp_docs"}'
   ```

5. Poll until `complete` or `failed`:

   ```bash
   curl -sS "$BASE_URL/ingest/$JOB_ID" -H "Authorization: Bearer $API_KEY"
   ```

6. Check `docs_indexed` and `error` in the JSON response.

## Single-process note

Ingestion runs **in-process** (`BackgroundTasks`). Only one heavy job per API replica is practical; for very large corpora, run ingestion when traffic is low or scale to a dedicated worker later ([api/ingestion_schedule.py](../api/ingestion_schedule.py) documents a Cloud Run Job hook).

## Evals after refresh

Golden rows are categorized in [evals/golden_dataset.json](../evals/golden_dataset.json). After changing the corpus, re-run fast validation:

```bash
uv run pytest tests/test_golden_loader_unit.py tests/test_golden_specialist_profiles_unit.py -q
```

Full RAGAS (LLM cost): `RUN_EVAL=1`, `uv sync --group eval`, then [evals/ragas_eval.py](../evals/ragas_eval.py) (see [AGENTS.md](../AGENTS.md)).

Optional CI: [.github/workflows/eval-manual.yml](../.github/workflows/eval-manual.yml) (`workflow_dispatch`) runs golden validation + RAGAS `--dry-run` without calling a judge model.

## Demo

After indexing, [demo/querymesh-demo.html](../demo/querymesh-demo.html) can target the same API (set `BASE_URL`, `API_KEY`, and `CORS_ALLOW_ORIGINS` if needed).
