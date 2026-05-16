# QueryMesh

Multi-agent GCP knowledge assistant. A natural-language query arrives, an orchestrator routes it to specialist agents (RAG, code generation, BigQuery analytics), and a synthesizer assembles one coherent response. Built on FastAPI, LangGraph, Vertex AI (Gemini + embeddings + reranking), Qdrant, Postgres, and Redis.

```
POST /query
    │
    ▼
echo  (request stub / multi-turn message append)
    │
    ▼
Orchestrator  (Gemini, temp=0 — classifies into retrieval / code_generation / analytics)
    │
    ├── retrieve  (dense search → Qdrant; skipped when orchestrator omits retrieval intent)
    │
    ├── specialists  (run concurrently when orchestrator sets parallel: true)
    │     ├── Analytics Agent  → generates + runs read-only BigQuery SQL
    │     └── Code Agent       → generates Python; optionally executes in E2B sandbox
    │
    ├── rag_structured  (structures retrieval hits into cited JSON)
    │
    └── synthesizer  (renders final answer; only node that may call save_memory)
```

---

## Contents

1. [Architecture overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [One-time setup](#one-time-setup)
4. [Running locally](#running-locally)
5. [RAG corpus](#rag-corpus)
6. [Web UI](#web-ui)
7. [Testing](#testing)
8. [Evaluations](#evaluations)
9. [Deploying to GCP](#deploying-to-gcp)
10. [Environment variables](#environment-variables)
11. [Further reading](#further-reading)

---

## Architecture overview

High-level system view (source: [`docs/architecture/QueryMesh - System Architecture.excalidraw`](docs/architecture/QueryMesh%20-%20System%20Architecture.excalidraw); dark variant: `QueryMesh - System Architecture_dark.png`).

![QueryMesh system architecture](docs/architecture/QueryMesh%20-%20System%20Architecture.png)

GCP production topology (source: [`docs/architecture/QueryMesh — GCP Infrastructure.excalidraw`](docs/architecture/QueryMesh%20%E2%80%94%20GCP%20Infrastructure.excalidraw)).

![QueryMesh GCP infrastructure](docs/architecture/QueryMesh%20%E2%80%94%20GCP%20Infrastructure.png)


| Layer              | Technology                        | Configuration                                                                                   |
| ------------------ | --------------------------------- | ----------------------------------------------------------------------------------------------- |
| API                | FastAPI (`api/`)                  | Bearer auth, sessions, rate limiting, `/query`, `/ingest`, **`/eval-reports`**                                     |
| Orchestration      | LangGraph (`graph/pipeline.py`)   | `GRAPH_MESSAGE_HISTORY_MAX` (default 10 tail messages)                                          |
| LLM — all agents   | Vertex AI Gemini                  | `VERTEX_LLM_MODEL` (default `gemini-2.5-flash`)                                                 |
| Embeddings         | Vertex AI                         | `VERTEX_EMBEDDING_MODEL` (default `text-embedding-005`)                                         |
| Semantic reranking | Vertex Discovery Engine           | `VERTEX_RANKING_MODEL` (default `semantic-ranker-fast-004`); toggle with `RAG_VERTEX_RERANK`    |
| Vector store       | Qdrant                            | `QDRANT_URL`, `QDRANT_COLLECTION` (default `gcp_docs`); local Docker or Cloud Run               |
| Corpus             | Text / PDF / Markdown files       | `INGESTION_GCP_DOCS_DIR`; default corpus is Google Cloud Next '26                               |
| Checkpointing      | Postgres via `AsyncPostgresSaver` | `DATABASE_URL`; multi-turn memory keyed on `{user_id}:{session_id}`                             |
| Session envelope   | Redis                             | `REDIS_URL`; 24 h TTL; graph checkpoint is source of truth for state                            |
| Long-term memory   | Postgres `user_memory`            | Top-5 rows compacted to 256 tokens; loaded before orchestrator on every request                 |
| Auth               | HMAC-SHA256 API keys              | `API_KEY_PEPPER`; keys resolved server-side, never trusted from client                          |
| Rate limiting      | slowapi                           | `QUERY_RATE_LIMIT` (default `60/minute`); storage via `RATE_LIMIT_STORAGE_URI` or `REDIS_URL`   |
| Observability      | Langfuse (hosted SaaS)            | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`; per-request traces, token counts, eval uploads    |
| Evals              | RAGAS                             | Judge LLM: `VERTEX_LLM_MODEL`; embeddings: `text-embedding-005` (fixed)                         |
| Eval snapshots     | Postgres `eval_reports`           | Persist with `EVAL_PERSIST_DATABASE=1` or `--persist` (Alembic `005_eval_reports_table`); **`GET /eval-reports`**; browser UI at **`/eval`** (`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL` for Langfuse trace links) |
| Code sandbox       | E2B                               | `E2B_API_KEY`; isolated Python execution, 15 s wall, 64 KiB output cap, no GCP creds in sandbox |
| Analytics          | BigQuery                          | `BIGQUERY_PROJECT_ID`, `BIGQUERY_DATASET`; read-only SQL, SELECT/WITH only                      |
| Account portal     | FastAPI + Google OAuth + JWT      | `PORTAL_JWT_SECRET` + Google OAuth client + `PORTAL_FRONTEND_BASE_URL`; API key minting unchanged |
| CORS               | FastAPI middleware                | `CORS_ALLOW_ORIGINS` (e.g. `https://your-web-app.vercel.app`)                                   |


---

## Prerequisites

**Required:**

- **GCP project** with [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — `gcloud auth application-default login`
- **Vertex AI API** enabled on the project

**For local development only:**

- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**
- **Docker** (local Postgres, Redis, and Qdrant via `infra/docker-compose.yml`)

**Optional:**

- **E2B API key** for the code execution sandbox
- **Langfuse account** (free at [cloud.langfuse.com](https://cloud.langfuse.com)) for traces and eval dashboards
- **Node.js 20.x** only if you develop the Next.js UI with `npm run dev` outside Docker (same major as [`web/Dockerfile`](web/Dockerfile); **default:** use Docker — see [Web UI](#web-ui))

---

## One-time setup

### Track A — Production (GCP, recommended)

```bash
# 1. Clone
git clone https://github.com/axa797/QueryMesh.git && cd QueryMesh

# 2. Point at your GCP project
gcloud config set project YOUR_PROJECT_ID

# 3. Bootstrap — enables APIs, creates Artifact Registry, Secret Manager secrets,
#    IAM bindings, and two Cloud Build triggers (app deploy + Terraform apply).
#    You will be prompted for each secret value.
bash scripts/bootstrap_gcp.sh

# 4. Provision infrastructure (Cloud SQL, Memorystore Redis, Qdrant on Cloud Run, VPC connector)
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in project_id and region
terraform init && terraform apply

# 5. Kick off the first deploy
#    Copy the suggested command from:
terraform output deploy_command
#    Run that command — Cloud Build fetches corpus, builds image, migrates DB, deploys, ingests.
```

After this, every `git push origin main` deploys automatically.

### Track B — Local development

```bash
./scripts/prepare_local.sh          # Docker Compose: Postgres, Redis, Qdrant, web (:3000); ensures corpus dir exists
cp .env.example .env                # if you do not already have `.env`
# Edit .env: set API_KEY_PEPPER and GOOGLE_CLOUD_PROJECT (if using Vertex)

uv sync
uv run --env-file .env alembic upgrade head
PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py  # prints raw key once — save it
```

See `docs/local_dev.md` for the full local walkthrough.

---

## Running locally

```bash
PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**Health check:**

```bash
curl -s http://127.0.0.1:8000/health | jq .
# { "status": "ok", "services": { "postgres": true, "redis": true, "qdrant": true } }
```

**Send a query:**

```bash
curl -sS http://127.0.0.1:8000/query \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the two new TPU chip variants announced at Next 26?"}' | jq .
```

The JSON body includes top-level `session_id`, `trace_id`, `latency_ms`, and a **`response`** object (`status`, **`synthesis`** with the main answer text, **`source_cards`**, plus structured fields such as `rag_structured`, `analytics_structured`, `code_structured` when those agents ran).

**Model overrides** — any of these can be set in `.env` or as environment variables:

```bash
VERTEX_LLM_MODEL=gemini-2.0-flash-001     # swap the generative model for all agents
VERTEX_EMBEDDING_MODEL=text-embedding-005  # embedding model for ingest + query-time search
VERTEX_RANKING_MODEL=semantic-ranker-fast-004  # Discovery Engine reranker
RAG_VERTEX_RERANK=true                     # enable/disable reranking (requires Discovery Engine API)
```

---

## RAG corpus

The corpus is a directory of text, Markdown, or PDF files indexed into Qdrant. It is configured entirely through environment variables — the pipeline does not hard-code any filenames or counts.


| Variable                        | Default                                                          | Purpose                                             |
| ------------------------------- | ---------------------------------------------------------------- | --------------------------------------------------- |
| `INGESTION_GCP_DOCS_DIR`        | `./corpus/gcp_docs` (local) / `/app/corpus/gcp_docs` (Cloud Run) | Directory the ingest pipeline reads from            |
| `QDRANT_COLLECTION`             | `gcp_docs`                                                       | Qdrant collection to index into                     |
| `INGESTION_RECREATE_COLLECTION` | `false`                                                          | Drop and recreate the collection on each ingest run |


**Default corpus:** Google Cloud Next '26 blog posts and announcement pages, fetched by `scripts/fetch_next26_corpus.py`. To use a different corpus, point `INGESTION_GCP_DOCS_DIR` at any directory of supported files.

**Refresh the default corpus (or re-index after a model change):**

```bash
# 1. Fetch latest pages (--clean removes old files first)
PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py --clean

# 2. Drop the existing Qdrant collection
curl -sS -X DELETE "http://localhost:6333/collections/gcp_docs" | jq .

# 3. Trigger ingest (API must be running)
BASE_URL=http://127.0.0.1:8000
JOB=$(curl -sS -X POST "$BASE_URL/ingest" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"gcp_docs"}' | jq -r .job_id)

# 4. Poll until complete
until curl -sS "$BASE_URL/ingest/$JOB" -H "Authorization: Bearer $API_KEY" | \
      jq -e '.status == "complete"' > /dev/null 2>&1; do sleep 5; done
echo "Indexed $(curl -sS "$BASE_URL/ingest/$JOB" -H "Authorization: Bearer $API_KEY" | jq .docs_indexed) chunks"
```

In production, the Cloud Build pipeline automatically re-fetches and re-indexes the corpus when `ingestion/` or `scripts/fetch_next26_corpus.py` change, or when the Qdrant collection is empty (e.g. first deploy).

See `docs/corpus_runbook.md` for the full runbook.

---

## Web UI

A Next.js frontend in `web/` provides Google sign-in, API key management, chat against `POST /query`, and eval reports at **`/eval`**. The **`/eval`** link appears in the top nav only when you are signed in (portal JWT). Requires `PORTAL_JWT_SECRET`, Google OAuth credentials, **`GOOGLE_OAUTH_REDIRECT_URI`** (API origin), and **`PORTAL_FRONTEND_BASE_URL`** (Next origin where `/oauth/callback` lives).

**Local:** run the UI **in Docker always** (`infra/docker-compose.yml` includes **`web`**). From the repo root:

```bash
docker compose -f infra/docker-compose.yml up -d
# docker compose ... up -d --build web   # after changing NEXT_PUBLIC_* in compose
```

→ [http://localhost:3000](http://localhost:3000). Run uvicorn on the host at **8000** (or adjust `NEXT_PUBLIC_*` **`web.build.args`** in Compose and **`--build`** again).

`NEXT_PUBLIC_QUERYMESH_URL` and **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** are **baked at image build time**. They must be URLs the **browser** can reach (your public Cloud Run API URL in production).

See `web/README.md` — **do not rely on `npm run dev`** for day-to-day use unless you are editing the frontend.

**Option A — Cloud Run (GCP credits, no Vercel):**

1. Deploy the **API** first so it has a public URL.
2. **First run:** `gcloud builds submit --config infra/cloudbuild-web.yaml` (from repo root, project set to your GCP project). This resolves the live `api` URL, builds `[web/Dockerfile](web/Dockerfile)`, pushes to Artifact Registry, and deploys service `**web`**.
3. **Ongoing:** push changes under `web/` on `main` — the `**web-deploy`** trigger runs the same config (created by `[scripts/bootstrap_gcp.sh](scripts/bootstrap_gcp.sh)` for new setups). Existing projects can add that trigger manually to match.
4. **CORS:** On the `**api`** Cloud Run service, set `CORS_ALLOW_ORIGINS` to your web origin (the build logs print the `web` URL). Comma-separate multiple origins if needed. Without this, the browser cannot call the API.

If your `**deploy**` trigger was created before `web/**` was added to ignored files, update it so **ignored files** includes `web/`** (in addition to `infra/terraform/**`). That avoids running the full API pipeline on web-only commits.

**Option B — Vercel:** (alternate to Docker-hosted web)

1. Import the repo on [vercel.com](https://vercel.com), **root directory `web`**
2. Set `NEXT_PUBLIC_QUERYMESH_URL=https://<your-cloud-run-api-url>` and **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** as needed.
3. Same **CORS** rule on the API for your `*.vercel.app` origin

See `web/README.md` for Compose build args and **`npm run dev`** (optional only).

---

## Testing

With Postgres, Redis, and Qdrant reachable (e.g. `docker compose -f infra/docker-compose.yml up -d postgres redis qdrant`) and the env exports below, the full unit suite runs without GCP credentials:

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/querymesh
export API_KEY_PEPPER=local-dev-pepper
export REDIS_URL=redis://127.0.0.1:6379/0
export QDRANT_URL=http://127.0.0.1:6333
export RATE_LIMIT_STORAGE_URI=memory://
uv run pytest -q
# Expected: 86 passed, 6 deselected (integration + eval markers require live services/LLM)
```

CI runs the same suite on every push via `.github/workflows/ci.yml` (Ruff + pytest).

---

## Evaluations

Evals use **RAGAS** (faithfulness, answer relevancy, context precision, context recall) scored against **live retrieval output** from the indexed corpus — not synthetic data.

- **Judge LLM:** follows `VERTEX_LLM_MODEL` (same model the agents use)
- **Embeddings:** `text-embedding-005` (fixed in `evals/ragas_eval.py`)
- Scores are uploaded to Langfuse as a `ragas-eval` trace when Langfuse keys are configured

**Scores from the last run** (10 retrieval rows, `gemini-2.5-flash` judge, reranking enabled):


| Metric            | Score |
| ----------------- | ----- |
| Faithfulness      | 0.95  |
| Answer relevancy  | 0.70  |
| Context precision | 0.48  |
| Context recall    | 0.72  |


Scores vary with corpus content, `VERTEX_LLM_MODEL`, and `RAG_VERTEX_RERANK`. Re-run after any of these change.

**Run evals:**

```bash
# 1. Harvest live retrieval contexts and model answers (requires running API + indexed corpus)
PYTHONPATH=. uv run --env-file .env python evals/harvest.py --categories retrieval,code_generation
# Writes evals/harvested_dataset.json

# 2. Score with RAGAS (calls Vertex AI — cost ~$1–2 for --limit 10)
uv sync --group eval
RUN_EVAL=1 PYTHONPATH=. uv run --group eval --env-file .env \
  python -m evals.ragas_eval --harvested --limit 10

# Persist aggregate + per-row scores to Postgres (same DATABASE_URL + `alembic upgrade head`)
RUN_EVAL=1 PYTHONPATH=. uv run --group eval --env-file .env \
  python -m evals.ragas_eval --harvested --limit 10 --persist
```

**Persist snapshots** when you append **`--persist`** or set **`EVAL_PERSIST_DATABASE=1`** (requires revision **`005_eval_reports_table`**). Optional: **`EVAL_TRIGGER`**, **`GITHUB_SHA`** / **`GIT_COMMIT`**. Automated **`pytest -m integration`** suites that mint API keys assume Postgres is migrated locally; omit integration runs on DB-less runners.

Browsing: **`/eval`** in the Docker web image (Compose **`web.build.args`**) — set **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** there (or `web/.env.local` only when using **`npm run dev`**).


---

## Deploying to GCP

All infrastructure is defined in `infra/`. Deployment is fully automated via Cloud Build — no manual `gcloud run deploy` needed after setup.

### One-time bootstrap (run once from Cloud Shell or locally)

```bash
bash scripts/bootstrap_gcp.sh
```

This enables all required GCP APIs, creates the Artifact Registry repository with a cleanup policy (keeps 5 most recent images), stores secrets in Secret Manager, configures IAM, and creates two Cloud Build triggers:

- `**deploy**` — fires on every push to `main`; builds and deploys the API
- `**tf-apply**` — fires when `infra/terraform/**` changes; runs `terraform apply`

### Provision infrastructure (run once)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id and region
terraform init && terraform apply
```

Provisions: Cloud SQL (Postgres 16), Memorystore (Redis 7), Qdrant on Cloud Run (`min-instances=1`), VPC Access Connector, and IAM bindings. Run `terraform output deploy_command` for the exact `gcloud builds submit` invocation with all required substitutions.

### Every deploy

```bash
git push origin main
```

The Cloud Build pipeline runs automatically:

1. **Fetch corpus** — runs `scripts/fetch_next26_corpus.py` (skipped if files already present)
2. **Build image** — corpus baked in at `/app/corpus/gcp_docs`
3. **Scan image** — checks for accidentally baked-in secrets
4. **Push** to Artifact Registry
5. **Migrate** — runs `alembic upgrade head` via Cloud SQL Auth Proxy
6. **Deploy** to Cloud Run
7. **Prune** old images (keeps 5 most recent)
8. **Ingest** — triggers `POST /ingest` only if Qdrant is empty **or** ingestion/corpus files changed

### Required secrets in Secret Manager


| Secret                | Description                                                                                                                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `API_KEY_PEPPER`      | Long random string for HMAC API key digests                                                                                                                                                                                                       |
| `DB_PASSWORD`         | Postgres password for the `querymesh` user                                                                                                                                                                                                        |
| `QDRANT_API_KEY`      | Auth key for the Qdrant Cloud Run service                                                                                                                                                                                                         |
| `QDRANT_URL`          | Internal Cloud Run URL for Qdrant (`terraform output qdrant_url`)                                                                                                                                                                                 |
| `INGEST_TOKEN`        | Service-to-service token for `POST /ingest` — generate with `openssl rand -hex 32`                                                                                                                                                                |
| `E2B_API_KEY`         | E2B sandbox API key                                                                                                                                                                                                                               |
| `LANGFUSE_PUBLIC_KEY` | Langfuse project public key                                                                                                                                                                                                                       |
| `LANGFUSE_SECRET_KEY` | Langfuse project secret key                                                                                                                                                                                                                       |
| `LANGFUSE_HOST`       | **Required for Langfuse Cloud US:** `https://us.cloud.langfuse.com`. Omit or use `https://cloud.langfuse.com` only for **EU** cloud (the SDK defaults to EU if unset, which yields **401** with US project keys). Self-hosted: your API base URL. |
| `PORTAL_JWT_SECRET`   | HS256 signing key for portal session JWT after Google OAuth                                                                                                                                                                                        |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth Web client secret (authorization code exchange on the API only)                                                                                                                                                                |


---

## Environment variables

Copy `.env.example` → `.env`. All variables are optional unless marked required.


| Variable                        | Required         | Default                                                 | Description                                                                                                                                              |
| ------------------------------- | ---------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `API_KEY_PEPPER`                | Yes              | —                                                       | HMAC secret for API key digests                                                                                                                          |
| `DATABASE_URL`                  | Yes              | —                                                       | `postgresql+asyncpg://...`                                                                                                                               |
| `REDIS_URL`                     | Yes              | —                                                       | `redis://...`                                                                                                                                            |
| `GOOGLE_CLOUD_PROJECT`          | For RAG/LLM      | —                                                       | Vertex AI project; agents fall back to offline mode if unset                                                                                             |
| `GOOGLE_CLOUD_LOCATION`         | For RAG/LLM      | `us-central1`                                           | Vertex AI region                                                                                                                                         |
| `VERTEX_LLM_MODEL`              | No               | `gemini-2.5-flash`                                      | Generative model for all agents (orchestrator, RAG, synthesizer, code, analytics) and RAGAS judge                                                        |
| `VERTEX_EMBEDDING_MODEL`        | No               | `text-embedding-005`                                    | Embedding model for ingest and query-time dense search                                                                                                   |
| `VERTEX_RANKING_MODEL`          | No               | `semantic-ranker-fast-004`                              | Discovery Engine reranker model                                                                                                                          |
| `RAG_VERTEX_RERANK`             | No               | `true`                                                  | Enable Vertex semantic reranking (requires Discovery Engine API)                                                                                         |
| `QDRANT_URL`                    | No               | `http://localhost:6333`                                 | Qdrant connection URL                                                                                                                                    |
| `QDRANT_API_KEY`                | No               | —                                                       | Qdrant auth key (required when Qdrant is deployed with auth enabled)                                                                                     |
| `QDRANT_COLLECTION`             | No               | `gcp_docs`                                              | Qdrant collection name for ingest and retrieval                                                                                                          |
| `INGESTION_GCP_DOCS_DIR`        | No               | `./corpus/gcp_docs`                                     | Directory of files to index; `/app/corpus/gcp_docs` in Cloud Run                                                                                         |
| `INGESTION_RECREATE_COLLECTION` | No               | `false`                                                 | Drop and recreate the Qdrant collection on each ingest run                                                                                               |
| `INGEST_TOKEN`                  | No               | —                                                       | Service-to-service token accepted by `POST /ingest` in addition to user API keys                                                                         |
| `PORTAL_JWT_SECRET`             | For web UI       | —                                                       | Portal session JWT HS256 signing; required with OAuth + `/account/api-keys`                                                                              |
| `PORTAL_FRONTEND_BASE_URL`      | For web UI       | —                                                       | Next origin for post-OAuth redirect to `/oauth/callback` (JWT in URL fragment).                                                                           |
| `GOOGLE_OAUTH_CLIENT_ID`        | For web UI       | —                                                       | Google OAuth Web client ID (Google Cloud Console).                                                                                                      |
| `GOOGLE_OAUTH_CLIENT_SECRET`    | For web UI       | —                                                       | Google OAuth client secret (token exchange stays on API).                                                                                                |
| `GOOGLE_OAUTH_REDIRECT_URI`     | For web UI       | —                                                       | Must match authorized redirect URI exactly, e.g. `https://<api-host>/account/oauth/google/callback`.                                                    |
| `BIGQUERY_PROJECT_ID`           | For analytics    | `GOOGLE_CLOUD_PROJECT`                                  | BigQuery project (defaults to `GOOGLE_CLOUD_PROJECT` if unset)                                                                                           |
| `BIGQUERY_DATASET`              | No               | `querymesh`                                             | BigQuery dataset for the analytics agent                                                                                                                 |
| `E2B_API_KEY`                   | For code sandbox | —                                                       | E2B API key; code generation still runs without it but execution is skipped                                                                              |
| `LANGFUSE_PUBLIC_KEY`           | No               | —                                                       | Enables Langfuse request traces                                                                                                                          |
| `LANGFUSE_SECRET_KEY`           | No               | —                                                       | Langfuse secret key                                                                                                                                      |
| `LANGFUSE_HOST`                 | No               | *(SDK default)* `https://cloud.langfuse.com` (EU cloud) | Regional API base. **Langfuse Cloud US:** set to `https://us.cloud.langfuse.com`. **EU:** leave unset or set explicitly. Self-hosted: your instance URL. |
| `LANGFUSE_TRACING_ENVIRONMENT`  | No               | —                                                       | Environment tag on traces (e.g. `production`)                                                                                                            |
| `QUERY_RATE_LIMIT`              | No               | `60/minute`                                             | Rate limit applied per API key on `POST /query`                                                                                                          |
| `RATE_LIMIT_STORAGE_URI`        | No               | `REDIS_URL`                                             | Storage backend for rate limiter; `memory://` in tests                                                                                                   |
| `CORS_ALLOW_ORIGINS`            | No               | —                                                       | Comma-separated allowed origins or `*`; required when browser and API are on different hosts                                                             |
| `GRAPH_MESSAGE_HISTORY_MAX`     | No               | `10`                                                    | Max tail messages formatted into agent prompts for multi-turn context                                                                                    |


Full reference: `.env.example`.

---

## Further reading

- `docs/local_dev.md` — detailed local development walkthrough
- `docs/corpus_runbook.md` — corpus management, Qdrant, and eval workflow
- `docs/production_infra.md` — supplemental Cloud SQL / Memorystore / Qdrant provisioning notes
- `docs/cloud_logging_metrics.md` — log-based metrics and GCP alert policies
- `infra/README.md` — Cloud Build pipeline structure and Terraform module map
- `web/README.md` — Next.js web UI setup and deployment options

