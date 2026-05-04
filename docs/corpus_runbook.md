# Corpus runbook

Public **GCP documentation** for RAG. The repo does not ship corpus files: use a local
directory, default `./corpus/gcp_docs` (`.env.example` → `INGESTION_GCP_DOCS_DIR`).
The directory is **gitignored** (`corpus/`).

## Refresh: Google Cloud Next '26 corpus

Fetches all ~69 pages from the Next '26 announcement wrap-up (blog posts + doc pages).
Use `--clean` to delete existing corpus files before fetching.

```bash
# 1. Fetch corpus (--clean replaces existing files)
PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py --clean

# 2. Start Docker services if not already running
docker compose -f infra/docker-compose.yml up -d

# 3. Drop the Qdrant collection (pick one):
#    Option A — direct REST (no API server needed, recommended):
curl -sS -X DELETE "http://localhost:6333/collections/gcp_docs" | jq .
#    Option B — let the indexer drop it (set once in .env, remove after first ingest):
echo "INGESTION_RECREATE_COLLECTION=true" >> .env

# 4. Start the API
PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 5. Trigger ingest
BASE_URL=http://127.0.0.1:8000
JOB=$(curl -sS -X POST "$BASE_URL/ingest" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"gcp_docs"}' | jq -r .job_id)

# 6. Poll until complete
until curl -sS "$BASE_URL/ingest/$JOB" -H "Authorization: Bearer $API_KEY" | \
      jq -e '.status == "complete"' > /dev/null 2>&1; do
  echo "Waiting ..."; sleep 5
done
echo "Corpus indexed."

# 7. Re-harvest eval data against the new corpus
PYTHONPATH=. uv run python evals/harvest.py --categories retrieval,code_generation
```

## Current corpus

**~69 HTML pages** from [`scripts/fetch_next26_corpus.py`](../scripts/fetch_next26_corpus.py):
blog posts and doc pages from the Google Cloud Next '26 260-announcement wrap-up.

Coverage: AI/agent platform, infrastructure (TPU 8th gen, Compute, GKE, Cloud Run),
data/analytics (BigQuery, Spanner, Looker), security (Wiz, Fraud Defense, Model Armor),
networking, storage, Firebase, and partner announcements.

To add individual pages, drop any `.md` or `.pdf` file under `corpus/gcp_docs/` and
re-run `POST /ingest` — the indexer upserts with deterministic point IDs so re-runs are safe.

## Adding custom PDFs

1. Browse [Google Cloud whitepapers](https://cloud.google.com/whitepapers/) — each entry links a `.pdf`.
2. Save into `corpus/gcp_docs/` with a readable filename.
3. Re-run `POST /ingest` — no need to drop the collection for additions.

## Prerequisites

- **Docker:** `docker compose -f infra/docker-compose.yml up -d` — Postgres, Redis, Qdrant up.
- **ADC:** `gcloud auth application-default login` — Vertex embeddings require this.
- `GOOGLE_CLOUD_PROJECT` set and Qdrant reachable (`QDRANT_URL` or local default).
- **Alembic:** `uv run alembic upgrade head` (includes `ingestion_jobs` table).

## Corpus layout

```text
corpus/
└── gcp_docs/
    ├── next26-day1-keynote-recap.md
    ├── next26-geap-adk.md
    └── ...
```

## Refresh workflow (incremental)

1. Add or replace files under `corpus/gcp_docs/`.
2. Set `INGESTION_RECREATE_COLLECTION=true` in `.env` **only** when switching embedding
   models or needing a clean slate — otherwise upsert handles duplicates safely.
3. `POST /ingest {"source":"gcp_docs"}` and poll `GET /ingest/{job_id}` until `complete`.

## Single-process note

Ingestion runs in-process (`BackgroundTasks`). One heavy job per API replica is practical;
for large corpora run ingestion during low-traffic windows or wire up a Cloud Run Job
([api/ingestion_schedule.py](../api/ingestion_schedule.py) documents the hook).

## Evals after refresh

```bash
# Structural validation (no LLM)
uv run pytest tests/test_golden_loader_unit.py -q

# Harvest live contexts + model answers (skip analytics — requires BigQuery)
PYTHONPATH=. uv run python evals/harvest.py --categories retrieval,code_generation

# Full RAGAS scoring (LLM judge via Vertex — has cost)
uv sync --group eval
RUN_EVAL=1 PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --harvested

# Optional manual CI trigger (golden validation + dry-run, no judge LLM)
# .github/workflows/eval-manual.yml — workflow_dispatch in GitHub Actions UI
```
