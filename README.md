# querymesh

Multi-agent GCP knowledge assistant. A natural-language query arrives, an orchestrator routes it to specialist agents (RAG, code generation, BigQuery analytics), and a synthesizer assembles one coherent response. Built on FastAPI, LangGraph, Vertex AI (Gemini + embeddings), Qdrant, Postgres, and Redis.

```
POST /query
    │
    ▼
Orchestrator (Gemini, temperature=0)
    │
    ├── RAG Agent          → dense search over GCP Next '26 corpus (Qdrant + Vertex embeddings)
    ├── Code Agent         → generates code, optionally executes in E2B sandbox
    └── Analytics Agent    → generates + runs read-only BigQuery SQL
    │
    ▼
Synthesizer (renders final answer; only node allowed to call save_memory)
```

---

## Contents

1. [Architecture overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [One-time setup](#one-time-setup)
4. [Running the stack](#running-the-stack)
5. [RAG corpus](#rag-corpus)
6. [Web UI](#web-ui)
7. [Testing](#testing)
8. [Evaluations](#evaluations)
9. [Deploying to Cloud Run](#deploying-to-cloud-run)
10. [Environment variables](#environment-variables)

---

## Architecture overview

| Layer | Technology | Purpose |
|---|---|---|
| API | FastAPI (`api/`) | Bearer auth, sessions, rate limiting, `/query`, `/ingest` |
| Orchestration | LangGraph (`graph/pipeline.py`) | DAG: echo → orchestrator → retrieve → specialists → RAG → synthesizer |
| LLM | Vertex AI Gemini (`gemini-2.5-flash`) | Orchestrator routing, RAG structured output, synthesizer |
| Embeddings | Vertex AI `text-embedding-005` | Ingest + query-time dense search |
| Vector store | Qdrant (local Docker / Cloud Run) | 491+ chunks from 68 Next '26 corpus pages |
| Checkpointing | Postgres via `AsyncPostgresSaver` | Multi-turn memory per `thread_id = {user_id}:{session_id}` |
| Session | Redis | 24h session envelope; checkpoint is source of truth for graph state |
| Long-term memory | Postgres `user_memory` | Top-5 rows compacted to 256 tokens; loaded before orchestrator |
| Observability | Langfuse (hosted SaaS) | Per-request traces, token counts, eval score upload |
| Evals | RAGAS + DeepEval | Faithfulness / relevancy / precision / recall against harvested corpus |
| Code sandbox | E2B | Isolated Python execution, 15s wall, 64KiB output cap, no GCP creds |
| Analytics | BigQuery | Read-only SQL, SELECT/WITH only, row + byte caps |

---

## Prerequisites

- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**
- **Docker** (for local Postgres, Redis, and Qdrant)
- **GCP project** with Vertex AI API enabled — `gcloud auth application-default login`
- **Node.js 18+** (only if running the Next.js web UI)

Optional:
- **E2B API key** for the code execution sandbox
- **Langfuse account** (free at [cloud.langfuse.com](https://cloud.langfuse.com)) for traces + eval dashboards
- **BigQuery** dataset bootstrapped with `scripts/bootstrap_bq.py` for the analytics agent

---

## One-time setup

```bash
# 1. Clone and prepare
./scripts/prepare_local.sh          # creates .venv, installs deps, copies .env.example

cp .env.example .env
# Required edits:
#   API_KEY_PEPPER=<any long random string>
#   GOOGLE_CLOUD_PROJECT=<your-gcp-project>
# Optional:
#   PORTAL_JWT_SECRET=<secret>       # enables browser signup/login
#   LANGFUSE_PUBLIC_KEY / SECRET_KEY # enables traces
#   E2B_API_KEY                      # enables code sandbox
#   CORS_ALLOW_ORIGINS=*             # enables browser demo

# 2. Start Docker services (Postgres, Redis, Qdrant)
docker compose -f infra/docker-compose.yml up -d

# 3. Run database migrations
uv run alembic upgrade head

# 4. Mint your first API key (printed once — save it)
PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py
```

---

## Running the stack

```bash
PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**Health check:**

```bash
curl -s http://127.0.0.1:8000/health | jq .
# Expected: { "postgres": true, "redis": true, "qdrant": true }
```

**Send a query:**

```bash
curl -sS http://127.0.0.1:8000/query \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the two new TPU chip variants announced at Next 26?"}' | jq .
```

The response includes `message` (user-facing answer), `trace_id` (Langfuse link), `session_id` (pass back for multi-turn), `latency_ms`, and structured outputs from each agent that ran (`rag_structured`, `analytics_structured`, `code_structured`).

---

## RAG corpus

The corpus is the **Google Cloud Next '26** 260-announcement wrap-up: 68 blog posts and doc pages covering AI/agent platform, infrastructure, data/analytics, security, Firebase, and more.

**Full corpus swap (first time or refresh):**

```bash
# Fetch all 68 pages, deleting old corpus files first
PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py --clean

# Drop the Qdrant collection (API server not needed)
curl -sS -X DELETE "http://localhost:6333/collections/gcp_docs" | jq .

# Start the API, then trigger ingest
BASE_URL=http://127.0.0.1:8000
JOB=$(curl -sS -X POST "$BASE_URL/ingest" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"gcp_docs"}' | jq -r .job_id)

# Poll until complete (~10–30s depending on machine)
until curl -sS "$BASE_URL/ingest/$JOB" -H "Authorization: Bearer $API_KEY" | \
      jq -e '.status == "complete"' > /dev/null 2>&1; do sleep 5; done
echo "Indexed $(curl -sS "$BASE_URL/ingest/$JOB" -H "Authorization: Bearer $API_KEY" | jq .docs_indexed) chunks"
```

What to expect: ~491 chunks indexed. `docs_indexed` returns the chunk count, not file count. See `docs/corpus_runbook.md` for the full runbook.

---

## Web UI

A Next.js frontend lives in `web/`. It provides signup/login, API key management, and a chat interface against `POST /query`.

**Requires** `PORTAL_JWT_SECRET` in `.env` (enables the account portal endpoints).

```bash
cd web
cp .env.example .env.local         # set NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
npm install
npm run dev                         # → http://localhost:3000
```

Or via Docker (API URL baked at build time, defaults to `http://127.0.0.1:8000`):

```bash
docker compose -f infra/docker-compose.yml up -d --build web
```

The API needs `CORS_ALLOW_ORIGINS` to include `http://localhost:3000` (or `*` locally). See `web/README.md`.

---

## Testing

Fast test suite (no GCP, no Docker required):

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/querymesh
export API_KEY_PEPPER=local-dev-pepper
export REDIS_URL=redis://127.0.0.1:6379/0
export RATE_LIMIT_STORAGE_URI=memory://
uv run pytest -q
# Expected: 71 passed
```

CI runs the same suite on push via `.github/workflows/ci.yml` (Ruff + pytest).

---

## Evaluations

Evals use **RAGAS** (faithfulness, answer relevancy, context precision/recall) with Gemini as the judge LLM. They run against **live retrieval output** from the indexed corpus — not synthetic data.

**Scores from the last run (10 retrieval rows, Gemini 2.5 Flash judge):**

| Metric | Score |
|---|---|
| Faithfulness | 0.95 |
| Answer relevancy | 0.70 |
| Context precision | 0.48 |
| Context recall | 0.72 |

**Run evals after a corpus change:**

```bash
# 1. Harvest live retrieval contexts + model answers (needs running API + indexed corpus)
PYTHONPATH=. uv run --env-file .env python evals/harvest.py
# Writes evals/harvested_dataset.json

# 2. Score with RAGAS (calls Vertex AI — has cost; ~$1–2 for --limit 10)
uv sync --group eval
RUN_EVAL=1 GOOGLE_CLOUD_PROJECT=<project> GOOGLE_CLOUD_LOCATION=us-central1 \
  PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --harvested --limit 10
```

Scores are automatically uploaded to Langfuse as a `ragas-eval` trace (requires Langfuse keys). View at **Traces → filter name = "ragas-eval"** to compare runs over time.

---

## Deploying to Cloud Run

All infra code is in `infra/`. The full deployment guide is in `docs/production_infra.md`.

**Summary:**

```bash
# Build image and deploy to Cloud Run in us-central1
gcloud builds submit --config infra/cloudbuild.yaml
```

Before deploying, provision:
- **Cloud SQL** (Postgres) — see `docs/production_infra.md`
- **Memorystore** (Redis)
- **Qdrant** (Cloud Run sidecar or Qdrant Cloud)
- **Secret Manager** — `API_KEY_PEPPER`, `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`

After deploy, trigger a corpus ingest against the production URL the same way as locally.

Enable `RAG_VERTEX_RERANK=true` only after the Discovery Engine API is active and you've confirmed embeddings are working — it significantly improves context precision.

---

## Environment variables

Copy `.env.example` → `.env`. Key variables:

| Variable | Required | Description |
|---|---|---|
| `API_KEY_PEPPER` | Yes | HMAC secret for API key digests |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` |
| `REDIS_URL` | Yes | `redis://...` |
| `GOOGLE_CLOUD_PROJECT` | For RAG/LLM | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | For RAG/LLM | Default: `us-central1` |
| `PORTAL_JWT_SECRET` | For web UI | Enables account portal |
| `QDRANT_URL` | Optional | Default: `http://localhost:6333` |
| `LANGFUSE_PUBLIC_KEY` | Optional | Enables request traces + eval upload |
| `LANGFUSE_SECRET_KEY` | Optional | |
| `LANGFUSE_HOST` | Optional | Default: `https://cloud.langfuse.com` |
| `E2B_API_KEY` | Optional | Enables code sandbox execution |
| `RAG_VERTEX_RERANK` | Optional | Enable Vertex reranking (Discovery Engine API required) |
| `CORS_ALLOW_ORIGINS` | Optional | e.g. `http://localhost:3000` or `*` |

Full reference: `.env.example`.

---

## Further reading

- `spec.md` — full technical specification and design decisions
- `PROGRESS.md` — phase checklist and implementation notes
- `docs/local_dev.md` — detailed local development walkthrough
- `docs/corpus_runbook.md` — corpus swap, Qdrant management, eval workflow
- `docs/production_infra.md` — Cloud SQL / Memorystore / Qdrant provisioning
- `docs/cloud_logging_metrics.md` — log-based metrics and alert policies
- `AGENTS.md` — agent context for AI coding assistants
