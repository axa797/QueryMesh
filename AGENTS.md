# Agent context (querymesh)

Read this at the start of a session. **Authoritative product/technical detail lives in [spec.md](spec.md).**  
**Implementation status:** [PROGRESS.md](PROGRESS.md).

## What this project is

Multi-agent GCP knowledge assistant: FastAPI API, LangGraph orchestration, RAG (LlamaIndex + Qdrant + Vertex), optional BigQuery analytics agent, code agent with E2B (no GCP creds in sandbox). Hosted Langfuse v1; Postgres for identity + long-term memory + LangGraph checkpointer; Redis for session envelope + rate-limit storage.

## Stack (repo conventions)

- **Python 3.12**; **uv** + **[pyproject.toml](pyproject.toml)** (no `requirements.txt`; lockfile is `uv.lock`).
- **Lint / format:** [Ruff](https://docs.astral.sh/ruff/) only (`ruff check`, `ruff format`).
- **GCP auth:** [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) via `gcloud auth application-default login` — **no** service account JSON in the repo or `GOOGLE_APPLICATION_CREDENTIALS` in `.env`.
- **License:** proprietary — see [LICENSE](LICENSE).

## Non-negotiables from spec

- **Region:** `us-central1` for Vertex, Cloud Run, BigQuery alignment.
- **Auth:** `Authorization: Bearer <api_key>` only; resolve via HMAC-SHA256(key, `API_KEY_PEPPER`); never trust client-supplied user id.
- **Sessions:** Optional `session_id`; must belong to authenticated user or 403 with stable JSON shape; `thread_id = "{user_internal_id}:{session_id}"`.
- **Memory:** Synthesizer **only** may call `save_memory`; Redis holds envelope only — not full graph state.
- **Orchestrator:** Max **3** specialist fan-outs; routing temperature **0**; JSON retry once then RAG-only fallback.
- **Code agent / E2B:** No egress; no ADC in sandbox; **15s** wall, **64KiB** combined output cap, **2** concurrent sandboxes per replica (tune later).
- **Feature flag:** `RAG_VERTEX_RERANK` — prod default on, local default off (see [.env.example](.env.example)).

## Repo map (target layout)

See **§5 Repository structure** in `spec.md`. Key dirs: `agents/`, `graph/`, `ingestion/`, `tools/`, `memory/`, `api/`, `scripts/`, `evals/`, `observability/`, `infra/`, `docs/`.

## Development environment (Docker-first)

- **Do not** install project dependencies into the developer’s user profile or system Python (no `pip install` / `uv sync` on the host unless the human explicitly opts in).
- Run **services and tooling in Docker**: use [infra/docker-compose.yml](infra/docker-compose.yml) for local Qdrant, Redis, and Postgres; when a dev `Dockerfile` / compose `api` service exists, run the API, migrations, pytest, and linters **via** those images or `docker compose run --rm …` targets—not bare `python`/`uv` on the host.
- **Database schema:** with Postgres up and `DATABASE_URL` set (see [.env.example](.env.example)), run `uv run alembic upgrade head`. Revision `001_initial_schema` creates app tables (`users`, `api_keys`, `user_memory`) and LangGraph checkpoint tables, with `checkpoint_migrations` seeded for `langgraph-checkpoint-postgres`.
- **Auth:** set `API_KEY_PEPPER` in `.env`. Mint a key: `PYTHONPATH=. uv run python scripts/mint_api_key.py` (prints raw key once; digest is **HMAC-SHA256(api_key, pepper)** per spec §8). `POST /query` requires `Authorization: Bearer <raw_key>`.
- **Sessions (Redis):** `REDIS_URL` required for `/query` and for [Settings](api/settings.py) (mint script included). Envelope key `querymesh:session:{session_id}`, TTL **24h**; omit `session_id` in the body to mint; wrong/unknown session → **403** `invalid_session` (spec §8). `thread_id` for LangGraph is `{user_internal_id}:{session_id}` (spec §7).
- **Long-term memory reads:** [memory/longterm.py](memory/longterm.py) — top **5** rows, order **preference → context → history**, then **last_accessed DESC**; compact block **256 tokens** (whitespace token heuristic). Loaded on each **`POST /query`** before the orchestrator stub.
- **LangGraph:** Compiled pipeline in [graph/pipeline.py](graph/pipeline.py) (`echo` → `orchestrator` → `retrieve` → **`specialists`** → `rag_structured` → `synthesizer`). The **`specialists`** node runs BigQuery analytics and code generation; when the orchestrator sets `parallel: true` and both intents are active, they run concurrently (`asyncio.gather`). **`retrieve`** runs only when the orchestrator includes `retrieval`; otherwise retrieval-related outputs are empty or skipped. [memory/checkpointer.py](memory/checkpointer.py) uses Postgres via `AsyncPostgresSaver` (DSN: `postgresql+asyncpg://` → `postgresql://` for psycopg); `get_compiled_query_graph()` is the app singleton; [api/routes/query.py](api/routes/query.py) passes `configurable.thread_id` and merges Langfuse callbacks via [observability/instrumentation.py](observability/instrumentation.py). App [lifespan](api/main.py) shutdown disposes the compiled graph, then the checkpoint pool, then SQLAlchemy and Redis.
- **Langfuse (Phase 13+):** Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, optional `LANGFUSE_HOST` and **`LANGFUSE_TRACING_ENVIRONMENT`** in [.env.example](.env.example) / [api/settings.py](api/settings.py). Graph invoke metadata includes **`user_id`** (internal UUID string) for trace correlation. Traces use the LangChain `CallbackHandler` on each `/query` graph run; response `trace_id` is the root trace id (UUID hex); `flush()` runs after each request. **`ALERT_*` thresholds and naming** — [observability/gcp_monitoring.py](observability/gcp_monitoring.py); **log-based metrics + alert playbook** — [docs/cloud_logging_metrics.md](docs/cloud_logging_metrics.md).
- **RAG (Phase 8):** Ingestion [ingestion/loader.py](ingestion/loader.py), [ingestion/chunker.py](ingestion/chunker.py), [ingestion/indexer.py](ingestion/indexer.py) (Vertex `text-embedding-004` + Qdrant `QDRANT_COLLECTION`, default `gcp_docs`). Query-time dense search in [tools/retrieval_tool.py](tools/retrieval_tool.py); set `GOOGLE_CLOUD_PROJECT` for embeddings. `RAG_VERTEX_RERANK` is honored as a stub (logs when on).
- **Orchestrator (Phase 9):** [agents/orchestrator.py](agents/orchestrator.py) — Vertex Gemini (`VERTEX_LLM_MODEL` / `vertex_llm_model`, default `gemini-2.0-flash`), JSON intents + `rewritten_queries` + `parallel`; one repair pass then RAG-only fallback. `/query` includes `orchestrator` with `source` metadata.
- **RAG + Synthesizer (Phase 10):** [agents/rag_agent.py](agents/rag_agent.py) produces §6.2 structured JSON from retrieval hits; [agents/synthesizer.py](agents/synthesizer.py) renders the user-facing `message` and may return JSON `save_memory` → [tools/memory_tool.py](tools/memory_tool.py) (Postgres `user_memory`) **only from the synthesizer**. Offline paths when `GOOGLE_CLOUD_PROJECT` is unset. Synthesizer payload may include **`analytics_structured`** and **`code_structured`** when not skipped.
- **Analytics (Phase 11):** Bootstrap dataset + `doc_metadata` with ADC: `PYTHONPATH=. uv run python scripts/bootstrap_bq.py` (see [scripts/README.md](scripts/README.md) for IAM: `bigquery.jobUser` + dataset `bigquery.dataViewer` on the API principal). Settings: `BIGQUERY_PROJECT_ID` (optional; falls back to `GOOGLE_CLOUD_PROJECT`), `BIGQUERY_DATASET`, `BIGQUERY_LOCATION`. [agents/analytics_agent.py](agents/analytics_agent.py) generates read-only SQL; [tools/bigquery_tool.py](tools/bigquery_tool.py) enforces `SELECT`/`WITH` only and row/bytes caps.
- **Code agent (Phase 12):** [agents/code_agent.py](agents/code_agent.py) is the **only** caller of [tools/code_exec_tool.py](tools/code_exec_tool.py). E2B: `E2B_API_KEY`, `E2B_TEMPLATE_ID` (custom image from [e2b/Dockerfile](e2b/Dockerfile)); sandboxes use `allow_internet_access=False`, no GCP credentials in env. Defaults: 15s command timeout, 64KiB combined stdout/stderr cap, 2 concurrent runs per process (`api/settings.py`).
- **Rate limit (Phase 14):** `POST /query` is limited by [api/rate_limit.py](api/rate_limit.py) (slowapi + `limits` storage). Default **60/minute** per API key (`Authorization` hash); clients without Bearer fall back to client IP. Storage: `RATE_LIMIT_STORAGE_URI` or `REDIS_URL`. **`SlowAPIMiddleware`** runs the check **before** auth. **429** responses use `error: rate_limit_exceeded` (see [api/main.py](api/main.py)). **`/health`** is exempt. Pytest defaults to `memory://` via [tests/conftest.py](tests/conftest.py).
- **Ingestion API (Phase 15):** [api/routes/ingest.py](api/routes/ingest.py) — `POST /ingest` `{ "source": "gcp_docs" }` returns `{ "status": "started", "job_id" }`; poll `GET /ingest/{job_id}` for `status` (`queued` \| `running` \| `complete` \| `failed`) and `docs_indexed`. Set **`INGESTION_GCP_DOCS_DIR`** (default in [.env.example](.env.example): `./corpus/gcp_docs`, directory gitignored); requires **`GOOGLE_CLOUD_PROJECT`** and Qdrant. Phase 2 persists job rows in Postgres (**`ingestion_jobs`**); worker runs in **`BackgroundTasks`** ([api/ingestion_schedule.py](api/ingestion_schedule.py) documents Cloud Run Job hook). Run **`uv run alembic upgrade head`** after pulling migrations. **Corpus:** [docs/corpus_runbook.md](docs/corpus_runbook.md).
- **Browser demo (Phase 2):** [demo/querymesh-demo.html](demo/querymesh-demo.html) — set `BASE_URL` and `API_KEY` at top; enable **`CORS_ALLOW_ORIGINS=*`** (or a specific origin) in `.env` when the page is opened from `file://` or another host.
- **Eval harness (Phase 17):** [evals/golden_dataset.json](evals/golden_dataset.json) + [evals/golden_loader.py](evals/golden_loader.py). **RAGAS:** `uv sync --group eval`; default `python -m evals.ragas_eval` validates golden data only (no LLM); with **`RUN_EVAL=1`**, **`GOOGLE_CLOUD_PROJECT`**, and ADC, runs faithfulness / answer relevancy / context precision & recall on retrieval rows (Vertex via `langchain-google-vertexai`; model from **`VERTEX_LLM_MODEL`** / env). **DeepEval:** `RUN_EVAL=1 uv run --group eval pytest evals/test_deepeval_suite.py -v` — uses **`FaithfulnessMetric`** on a golden sample; configure provider keys per DeepEval defaults (often **`OPENAI_API_KEY`**) unless you swap the metric model. PR-style **`pytest`** excludes tests marked **`eval`** (see [pyproject.toml](pyproject.toml)); [tests/test_golden_loader_unit.py](tests/test_golden_loader_unit.py) stays in the fast suite.
- **Cloud Run / Cloud Build (Phase 18):** [infra/Dockerfile](infra/Dockerfile) builds the API; [infra/README.md](infra/README.md) describes Artifact Registry, Secret Manager (`API_KEY_PEPPER`, `E2B_API_KEY`, and optional `DATABASE_URL` / `REDIS_URL` / `QDRANT_URL` via **`_EXTRA_DEPLOY_ARGS`**). Submit **`gcloud builds submit --config infra/cloudbuild.yaml`** to push an image and deploy service **`api`** in **us-central1**; use **`infra/cloudbuild.pr.yaml`** for PR fast **`pytest`**.
- Copy [.env.example](.env.example) → `.env`; do not commit `.env`.
- **§13 Local development** in `spec.md` has command examples (adapt to containerized commands as targets are added).

### Checking GCP region / project

These read **gcloud CLI defaults**, not what a single API call uses (Vertex/BigQuery location is often explicit in code or `GOOGLE_CLOUD_LOCATION`).

```bash
gcloud config get-value project
gcloud config get-value compute/region
gcloud config get-value run/region
gcloud config list
```

For **Vertex AI**, confirm the location your app passes (env or code), e.g. `GOOGLE_CLOUD_LOCATION=us-central1` per spec.

## Git workflow

- **Solo development:** commit directly to `**main`**. Do not create feature branches (including `cursor/`*) unless the user explicitly asks for one.
- **Commit cadence:** After `ruff check`, `ruff format --check`, and fast `pytest` are green, commit in **small logical steps** (docs vs CI vs tests vs feature vs follow-up docs). New behavior should include **tests** before the feature commit when practical.

## How to work in this repo

1. Check **PROGRESS.md** for the current phase; prefer completing the next unchecked §15 item unless fixing bugs.
2. After meaningful progress, update **PROGRESS.md** (check boxes, **Current focus**, **Notes**, or checkpoint table).
3. Prefer small, reviewable commits on `**main`**; match existing layout and tooling.
4. When behavior or API is ambiguous, **cite `spec.md` section** in commit messages or notes rather than inventing requirements.
5. **CI:** [.github/workflows/ci.yml](.github/workflows/ci.yml) runs Ruff + fast `pytest` on push/PR when using GitHub; Cloud Build [infra/cloudbuild.pr.yaml](infra/cloudbuild.pr.yaml) remains the GCP PR path.

## Files agents should touch


| Purpose                     | File           |
| --------------------------- | -------------- |
| Requirements & architecture | `spec.md`      |
| Done / next                 | `PROGRESS.md`  |
| Env template                | `.env.example` |
| This context                | `AGENTS.md`    |


