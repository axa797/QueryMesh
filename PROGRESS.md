# querymesh — implementation progress

Single source of truth for **what is done** vs **spec §15 build order**.  
Update this file when starting or finishing a phase (short note under the item is enough).

**Spec:** [spec.md](spec.md)  
**Agent context:** [AGENTS.md](AGENTS.md) · **Local stack (no deploy):** [docs/local_dev.md](docs/local_dev.md)

## Current focus

- **Pre-deploy:** Local path is documented in [docs/local_dev.md](docs/local_dev.md); `/health` checks Postgres, Redis, and Qdrant. Track outstanding work in **Next steps (tracked)** below.
- **Phase 2** — Largely complete per [spec_phase2.md](spec_phase2.md). Remaining Phase 2-style items are mostly **operational** (GCP alert policies, first prod deploy), not code.

## Phase checklist (§15)

- **1. Repo scaffold** — Done: Python 3.12, uv, [pyproject.toml](pyproject.toml), Ruff, package layout per spec, [.env.example](.env.example), [LICENSE](LICENSE), [tests/test_health.py](tests/test_health.py). Dependencies in `pyproject.toml` only (no `requirements.txt`).
- **2. Infra primitives (local)** — Done: [infra/docker-compose.yml](infra/docker-compose.yml) — Qdrant, Redis, Postgres (`postgres` / `querymesh`); Langfuse env vars in [.env.example](.env.example) (optional; hosted SaaS per §11).
- **3. Postgres schema & migrations** — Done: Alembic [alembic/versions/001_initial_schema.py](alembic/versions/001_initial_schema.py) — `users`, `api_keys`, `user_memory`, LangGraph checkpoint tables + seeded `checkpoint_migrations`; [002](alembic/versions/002_ingestion_jobs_table.py) `ingestion_jobs`; `/health` probes Postgres, Redis, and Qdrant when URLs are set.
- **4. Auth middleware** — Done: [api/deps.py](api/deps.py) Bearer → [api/auth.py](api/auth.py) digest + lookup; stable 401 JSON; [scripts/mint_api_key.py](scripts/mint_api_key.py); stub [POST /query](api/routes/query.py).
- **5. Session layer** — Done: [memory/session_envelope.py](memory/session_envelope.py) — Redis envelope (`querymesh:session:{uuid}`), 24h TTL, optional `session_id` on [QueryRequest](api/schemas/query.py); mint or validate + **403** `invalid_session`; `thread_id` = `{user_id}:{session_id}`; [memory/redis_client.py](memory/redis_client.py); `/health` pings Redis.
- **6. Long-term memory reads** — Done: [memory/longterm.py](memory/longterm.py) — `load_top_k_memories` + `compact_to_token_budget` (§7: k=5, ordering, 256-token cap); wired into [POST /query](api/routes/query.py) before orchestrator stub (`has_memory` in response).
- **7. LangGraph skeleton** — Done: [graph/pipeline.py](graph/pipeline.py) — **echo → orchestrator → retrieve → specialists → RAG → synthesizer** (specialists: analytics + code when routed); [memory/checkpointer.py](memory/checkpointer.py) Psycopg pool + `AsyncPostgresSaver`; `config.configurable.thread_id`; `/query` passes `**user_id`** into graph for `save_memory`.
- **8. RAG vertical slice** — Done: [ingestion/loader.py](ingestion/loader.py) / [ingestion/chunker.py](ingestion/chunker.py) / [ingestion/indexer.py](ingestion/indexer.py) (+ [ingestion/embeddings.py](ingestion/embeddings.py)); Qdrant collection `gcp_docs` via settings; [tools/retrieval_tool.py](tools/retrieval_tool.py) + `**retrieve`** after orchestrator; Phase 2: `RAG_VERTEX_RERANK` → Discovery Engine ranker (see Phase 2 notes).
- **9. Orchestrator** — Done: [agents/orchestrator.py](agents/orchestrator.py) — Vertex Gemini (`vertex_llm_model`, default `gemini-2.0-flash`), `temperature=0`, JSON route; Pydantic validate; **retry** once with repair user prompt; **RAG-only** `fallback_parse` / `fallback_no_gcp`; intents capped at **3**. [graph/pipeline.py](graph/pipeline.py) node `**orchestrator`**; `/query` returns `**orchestrator`** (replaces stub key).
- **10. Synthesizer** — Done: [agents/rag_agent.py](agents/rag_agent.py) (§6.2 JSON) → [agents/synthesizer.py](agents/synthesizer.py) (§6.5 user `message` + optional `save_memory` in model JSON); [tools/memory_tool.py](tools/memory_tool.py) + [memory/longterm.py](memory/longterm.py) `insert_user_memory` — **only synthesizer** calls `save_memory`. `/query` includes `rag_structured`, `synthesis`; `status: ok`.
- **11. Analytics vertical slice** — Done: [scripts/bootstrap_bq.py](scripts/bootstrap_bq.py) + [scripts/README.md](scripts/README.md); [tools/bigquery_tool.py](tools/bigquery_tool.py) read-only SQL guard + caps; [agents/analytics_agent.py](agents/analytics_agent.py); graph `**analytics`** after `**retrieve`** when intent; `/query` includes `analytics_structured`.
- **12. Code agent + E2B** — Done: [e2b/Dockerfile](e2b/Dockerfile); [tools/code_exec_tool.py](tools/code_exec_tool.py) (15s wall, 64KiB combined output, concurrency 2, no egress); [agents/code_agent.py](agents/code_agent.py) (**only** E2B caller); graph `**code_generation`** after `**analytics`** when intent; `/query` includes `code_structured`; [scripts/README.md](scripts/README.md) E2B notes.
- **13. Parallel fan-out & synthesis** — Done: [graph/pipeline.py](graph/pipeline.py) `**specialists`** node — analytics + code in parallel when orchestrator `parallel: true`; [observability/instrumentation.py](observability/instrumentation.py) — Langfuse `CallbackHandler` on graph `ainvoke`, `flush` after request, `trace_id` in API; `langfuse` + `langchain` deps.
- **14. POST /query hard API** — Done: [api/rate_limit.py](api/rate_limit.py) slowapi `default_limits` + Redis (`RATE_LIMIT_STORAGE_URI` or `REDIS_URL`); per Bearer-hash key, IP fallback; limit enforced **before** auth via `SlowAPIMiddleware`; stable **429** JSON (`rate_limit_exceeded`); `/health` exempt; [tests/conftest.py](tests/conftest.py) `memory://` default for pytest; `QUERY_RATE_LIMIT` setting (`60/minute`).
- **15. Ingestion API** — Done: [api/routes/ingest.py](api/routes/ingest.py) `POST /ingest` + `GET /ingest/{job_id}`; Phase 2: [api/ingestion_job_store.py](api/ingestion_job_store.py) + Alembic `ingestion_jobs`; [api/ingestion_runner.py](api/ingestion_runner.py) + [api/ingestion_schedule.py](api/ingestion_schedule.py) (`BackgroundTasks`); [ingestion/indexer.py](ingestion/indexer.py) `RunIndexResult`; settings `INGESTION_GCP_DOCS_DIR`, `INGESTION_RECREATE_COLLECTION`; [tests/test_ingest_api_unit.py](tests/test_ingest_api_unit.py).
- **16. Observability & dashboards** — Done: [observability/gcp_monitoring.py](observability/gcp_monitoring.py) metric names + alert constants (stubs / log-based path); Langfuse `user_id` + `LANGFUSE_TRACING_ENVIRONMENT` on traces; [tests/test_gcp_monitoring_unit.py](tests/test_gcp_monitoring_unit.py).
- **17. Eval harness** — Done: [evals/golden_dataset.json](evals/golden_dataset.json) (30 rows), [evals/golden_loader.py](evals/golden_loader.py), [evals/ragas_eval.py](evals/ragas_eval.py), [evals/test_deepeval_suite.py](evals/test_deepeval_suite.py); `eval` pytest marker excluded from default runs; `RUN_EVAL=1` + `uv sync --group eval` for LLM judges.
- **18. Cloud Build & Run deploy** — Done: [infra/Dockerfile](infra/Dockerfile), [infra/cloudbuild.yaml](infra/cloudbuild.yaml) (Artifact Registry + Cloud Run **api** in **us-central1**), [infra/cloudbuild.pr.yaml](infra/cloudbuild.pr.yaml); [.dockerignore](.dockerignore); [infra/README.md](infra/README.md) (Secret Manager + IAM + Qdrant notes).

## Checkpoint gates (between phases)

From spec: **(a)** auth + session tests green before agents; **(b)** RAG path produces traces before enabling rerank in prod; **(c)** BigQuery bootstrap repeatable before Analytics eval cases; **(d)** E2B template pinned + regression test for sandbox timeouts before broad execution exposure.


| Gate                                | Status |
| ----------------------------------- | ------ |
| (a) Auth + session                  | ☑      |
| (b) RAG traces before prod rerank   | ☑      |
| (c) Repeatable BQ bootstrap         | ☑      |
| (d) E2B pinned + timeout regression | ☑      |


## Phase 2 (spec_phase2)

- **CI:** [.github/workflows/ci.yml](.github/workflows/ci.yml) — `ruff check`, `ruff format --check`, fast `pytest` on push/PR; stub `DATABASE_URL` / `API_KEY_PEPPER` / `REDIS_URL` / `RATE_LIMIT_STORAGE_URI=memory://` for imports.
- **Gate (a):** Session + stable 403 JSON + `thread_id` on LangGraph config — [tests/test_session_unit.py](tests/test_session_unit.py).
- **RAG rerank:** Discovery Engine `RankService` when `RAG_VERTEX_RERANK`; [tests/test_retrieval_rerank_unit.py](tests/test_retrieval_rerank_unit.py).
- **Persisted ingest:** `ingestion_jobs` table; in-process worker; [api/ingestion_schedule.py](api/ingestion_schedule.py) hook for future Cloud Run Job.
- **Ops dashboards:** [docs/cloud_logging_metrics.md](docs/cloud_logging_metrics.md); [infra/terraform/README.md](infra/terraform/README.md) (`log_metrics.tf.example`).
- **Local dev (pre-deploy):** [docs/local_dev.md](docs/local_dev.md), [scripts/prepare_local.sh](scripts/prepare_local.sh); demo [demo/querymesh-demo.html](demo/querymesh-demo.html); pytest: high `QUERY_RATE_LIMIT` + cache clear after rate-limit tests ([tests/conftest.py](tests/conftest.py), [tests/test_query_rate_limit.py](tests/test_query_rate_limit.py)).

---

## Next steps (tracked)

Use GitHub task lists (`- [ ]` / `- [x]`) or turn each line into an issue. Reconcile here when items ship.

### Before first production deploy

- Local smoke: [docs/local_dev.md](docs/local_dev.md) — compose up, `uv run --env-file .env alembic upgrade head`, mint key, `uvicorn` with `--env-file .env`, `GET /health` all services `true`, demo HTML + `CORS_ALLOW_ORIGINS`.
- Secrets: `API_KEY_PEPPER`, DB/Redis/Qdrant URLs, optional `E2B_`*, Langfuse keys per [infra/README.md](infra/README.md).
- Cloud Run (+ Qdrant if self-hosted): image from [infra/Dockerfile](infra/Dockerfile), `us-central1`, env aligned with `.env.example`.
- Log-based metrics + alert policies: [docs/cloud_logging_metrics.md](docs/cloud_logging_metrics.md) using `ALERT_`* in [observability/gcp_monitoring.py](observability/gcp_monitoring.py).

### After deploy / ongoing

- Enable `RAG_VERTEX_RERANK` only after Discovery Engine API + smoke; see [.env.example](.env.example).
- Cost/latency pass: candidate limits, models, rate limits — driven by Langfuse + `querymesh_query` stdout logs.
- **Phase 3 (optional scoping):** document goals (e.g. Cloud Run Job for ingest replacing `BackgroundTasks`, deeper dashboards). Prior backlog in Notes still lists historical phase bullets.

### Done recently (keep for audit trail)

- **Account portal (optional):** Signup/login JWT + API key lifecycle — [`POST /account/register`](api/routes/account.py), `POST /account/login`, `POST|GET /account/api-keys`, `POST /account/api-keys/{id}/revoke`. Uses same `users` / `api_keys` tables as [`scripts/mint_api_key.py`](scripts/mint_api_key.py). Set **`PORTAL_JWT_SECRET`** in `.env` ([`.env.example`](.env.example)). Alembic **`003_user_portal_login`**: `users.email`, `users.password_hash`. **`POST /query`** still requires Bearer **API key** only (spec §8).
- Local dev runbook + `prepare_local.sh`; `/health` includes real Qdrant ping ([memory/database.py](memory/database.py)).
- Phase 2 CI, persisted ingest jobs, rerank, structured `/query` logs, demo HTML, corpus runbook — see Phase 2 block above.

---

## Notes

*Use for decisions, blockers, or links to PRs. Newest first.*

- **2026-04:** Pre-deploy local stack documented; track remaining work under **Next steps (tracked)**.
- **Corpus runbook (Phase 2):** [docs/corpus_runbook.md](docs/corpus_runbook.md), golden analytics/code profile tests, `workflow_dispatch` eval validation workflow.
- Scaffold choices: Python **3.12**, **uv** + pyproject, **Ruff** only, **ADC only** (no SA JSON), **BIGQUERY_DATASET=querymesh**, local **Postgres** user/db **postgres** / **querymesh**, **Langfuse** env empty until §15.16, proprietary **LICENSE**; **GitHub Actions** CI for lint + fast tests ([.github/workflows/ci.yml](.github/workflows/ci.yml)); Cloud Build deploy unchanged.
- **Phase 3:** Alembic at repo root; LangGraph DDL aligned with `langgraph-checkpoint-postgres==3.0.5` `MIGRATIONS[0:11]`; non-CONCURRENT indexes for transactional migration.
- **Phase 4:** Bearer auth, `pydantic-settings`, async pool + session scope, `scripts/mint_api_key.py`, `POST /query` stub; 401 JSON matches spec shape pattern.
- **Phase 5:** Redis session envelope (24h TTL), `session_id` / `thread_id` for LangGraph, 403 stable JSON; settings require `REDIS_URL`.
- **Phase 6:** [memory/longterm.py](memory/longterm.py) Postgres read policy + compaction; `/query` loads memory before stub orchestrator; session unit tests monkeypatch DB load to avoid TestClient/asyncpg loop issues.
- **Phase 7:** [graph/pipeline.py](graph/pipeline.py) + [memory/checkpointer.py](memory/checkpointer.py) — LangGraph `StateGraph`, Postgres `AsyncPostgresSaver`, `thread_id` threading; unit tests use `MemorySaver`.
- **Phase 8:** Ingestion (`ingestion/`*), Vertex `text-embedding-005`, Qdrant upsert CLI ([ingestion/indexer.py](ingestion/indexer.py)), [tools/retrieval_tool.py](tools/retrieval_tool.py), graph `**retrieve`** node; `retrieval_hits` on `/query`; Phase 2: `RAG_VERTEX_RERANK` → Discovery Engine ranker (see Phase 2 section).
- **Phase 9:** [agents/orchestrator.py](agents/orchestrator.py) — Gemini routing + fallbacks; graph node `orchestrator`; `orchestrator.source` metadata on `/query`.
- **Phase 10:** RAG JSON ([agents/rag_agent.py](agents/rag_agent.py)), synthesizer ([agents/synthesizer.py](agents/synthesizer.py)), [tools/memory_tool.py](tools/memory_tool.py); graph nodes `rag_structured`, `synthesizer`; shared [agents/vertex.py](agents/vertex.py), [agents/jsonutil.py](agents/jsonutil.py).
- **Phase 11:** BigQuery bootstrap + IAM notes in [scripts/README.md](scripts/README.md); [agents/analytics_agent.py](agents/analytics_agent.py) + [tools/bigquery_tool.py](tools/bigquery_tool.py); graph `**analytics`** after `**retrieve`** when intent; Ruff + pytest green.
- **Phase 12:** [agents/code_agent.py](agents/code_agent.py) + [tools/code_exec_tool.py](tools/code_exec_tool.py); `e2b` dependency; synthesizer + `/query` carry `code_structured`; timeout regression test in [tests/test_code_exec_tool.py](tests/test_code_exec_tool.py).
- **Phase 13:** `**specialists`** merged node + parallel gather; Langfuse tracing; [tests/test_parallel_fanout_unit.py](tests/test_parallel_fanout_unit.py).
- **Phase 14:** slowapi + Redis rate limit on `POST /query`; sync `RateLimitExceeded` handler; [tests/test_query_rate_limit.py](tests/test_query_rate_limit.py).
- **Phase 15:** `POST /ingest` / `GET /ingest/{job_id}`; BackgroundTasks; [tests/test_ingest_api_unit.py](tests/test_ingest_api_unit.py).
- **Phase 16:** `user_id` on Langfuse graph metadata; `langfuse_tracing_environment`; [observability/gcp_monitoring.py](observability/gcp_monitoring.py) Cloud Monitoring naming + alert constants (export stub); `/query` debug metric log hook.
- **Phase 17:** [evals/](evals/) golden JSON + RAGAS / DeepEval runners; `eval` pytest marker; fast [tests/test_golden_loader_unit.py](tests/test_golden_loader_unit.py).
- **Phase 18:** [infra/Dockerfile](infra/Dockerfile) API image (`uv`, non-root); [infra/cloudbuild.yaml](infra/cloudbuild.yaml) / [infra/cloudbuild.pr.yaml](infra/cloudbuild.pr.yaml); [infra/README.md](infra/README.md) Secret Manager + deploy; `.dockerignore`.