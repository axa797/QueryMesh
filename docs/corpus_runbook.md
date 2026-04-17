# Corpus runbook (Phase 2)

Public **GCP documentation** for RAG: primarily **PDFs**, plus optional **Markdown exports** of selected HTML docs (see below). The repo does not ship corpus files: use a local directory, default `./corpus/gcp_docs` ([`.env.example`](../.env.example) → `INGESTION_GCP_DOCS_DIR`). The directory is **gitignored** (`corpus/`).

## Target size (spec)

- About **15–20 PDFs**, roughly **500–800 pages** total (Cloud Run, Vertex AI, BigQuery, GKE, Cloud Storage, …).
- Quality over quantity: keep headings and export quality high so section-aware chunking works.

## Where to get PDFs

Google no longer exposes a single “export all product docs as PDF” tree; use **official PDFs** only.

1. **Quick starter (recommended):** from repo root run  
   `./scripts/fetch_gcp_corpus_pdfs.sh`  
   This downloads **PDF whitepapers** plus a **curated set of [Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform)** documentation pages (HTML → `.md` text files) into `./corpus/gcp_docs/`. That platform is Google’s unified stack to **build, scale, govern, and optimize** enterprise agents (the primary doc surface Google is consolidating around). Edit URL lists in `scripts/fetch_gcp_corpus_pdfs.sh` / `scripts/fetch_gemini_enterprise_agent_platform_docs.py` to customize.
2. **Gemini Enterprise Agent Platform only (no PDFs):**  
   `PYTHONPATH=. uv run python scripts/fetch_gemini_enterprise_agent_platform_docs.py`
3. **Browse manually:** [Google Cloud whitepapers](https://cloud.google.com/whitepapers/) — each entry links a `.pdf`; save into `corpus/gcp_docs/` with readable filenames.
4. **Print from HTML (fallback):** open a [docs.cloud.google.com](https://docs.cloud.google.com/) page in the browser → **Print** → **Save as PDF** (quality varies; prefer native PDFs when possible).

Optional gated PDF: [Gemini Enterprise guidebook](https://cloud.google.com/resources/content/gemini-enterprise-guidebook-download) (marketing form; not scripted here).

The scripted fetch matches the spec’s **~15–20** primary-document starter goal; you can add more PDFs or `.md` exports under `corpus/gcp_docs/` as needed.

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
- `**GOOGLE_CLOUD_PROJECT`** set (and Qdrant reachable via `QDRANT_URL` / local default).
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