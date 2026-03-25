# querymesh — implementation progress

Single source of truth for **what is done** vs **spec §15 build order**.  
Update this file when starting or finishing a phase (short note under the item is enough).

**Spec:** [spec.md](spec.md)  
**Agent context:** [AGENTS.md](AGENTS.md)

## Current focus

- **Phase 13** — Parallel fan-out and synthesis (Langfuse spans).

## Phase checklist (§15)

- **1. Repo scaffold** — Done: Python 3.12, uv, [pyproject.toml](pyproject.toml), Ruff, package layout per spec, [.env.example](.env.example), [LICENSE](LICENSE), [tests/test_health.py](tests/test_health.py). Dependencies in `pyproject.toml` only (no `requirements.txt`).
- **2. Infra primitives (local)** — Done: [infra/docker-compose.yml](infra/docker-compose.yml) — Qdrant, Redis, Postgres (`postgres` / `querymesh`); Langfuse vars in [.env.example](.env.example) empty until observability (§15.16).
- **3. Postgres schema & migrations** — Done: Alembic [alembic/versions/001_initial_schema.py](alembic/versions/001_initial_schema.py) — `users`, `api_keys`, `user_memory`, LangGraph checkpoint tables + seeded `checkpoint_migrations`; `/health` probes Postgres when `DATABASE_URL` is set.
- **4. Auth middleware** — Done: [api/deps.py](api/deps.py) Bearer → [api/auth.py](api/auth.py) digest + lookup; stable 401 JSON; [scripts/mint_api_key.py](scripts/mint_api_key.py); stub [POST /query](api/routes/query.py).
- **5. Session layer** — Done: [memory/session_envelope.py](memory/session_envelope.py) — Redis envelope (`querymesh:session:{uuid}`), 24h TTL, optional `session_id` on [QueryRequest](api/schemas/query.py); mint or validate + **403** `invalid_session`; `thread_id` = `{user_id}:{session_id}`; [memory/redis_client.py](memory/redis_client.py); `/health` pings Redis.
- **6. Long-term memory reads** — Done: [memory/longterm.py](memory/longterm.py) — `load_top_k_memories` + `compact_to_token_budget` (§7: k=5, ordering, 256-token cap); wired into [POST /query](api/routes/query.py) before orchestrator stub (`has_memory` in response).
- **7. LangGraph skeleton** — Done: [graph/pipeline.py](graph/pipeline.py) — **echo → orchestrator → retrieve → specialists → RAG → synthesizer** (specialists: analytics + code when routed); [memory/checkpointer.py](memory/checkpointer.py) Psycopg pool + `AsyncPostgresSaver`; `config.configurable.thread_id`; `/query` passes **`user_id`** into graph for `save_memory`.
- **8. RAG vertical slice** — Done: [ingestion/loader.py](ingestion/loader.py) / [ingestion/chunker.py](ingestion/chunker.py) / [ingestion/indexer.py](ingestion/indexer.py) (+ [ingestion/embeddings.py](ingestion/embeddings.py)); Qdrant collection `gcp_docs` via settings; [tools/retrieval_tool.py](tools/retrieval_tool.py) + **`retrieve`** after orchestrator; `RAG_VERTEX_RERANK` wired (log-only until Vertex rerank lands).
- **9. Orchestrator** — Done: [agents/orchestrator.py](agents/orchestrator.py) — Vertex Gemini (`vertex_llm_model`, default `gemini-2.0-flash`), `temperature=0`, JSON route; Pydantic validate; **retry** once with repair user prompt; **RAG-only** `fallback_parse` / `fallback_no_gcp`; intents capped at **3**. [graph/pipeline.py](graph/pipeline.py) node **`orchestrator`**; `/query` returns **`orchestrator`** (replaces stub key).
- **10. Synthesizer** — Done: [agents/rag_agent.py](agents/rag_agent.py) (§6.2 JSON) → [agents/synthesizer.py](agents/synthesizer.py) (§6.5 user `message` + optional `save_memory` in model JSON); [tools/memory_tool.py](tools/memory_tool.py) + [memory/longterm.py](memory/longterm.py) `insert_user_memory` — **only synthesizer** calls `save_memory`. `/query` includes `rag_structured`, `synthesis`; `status: ok`.
- **11. Analytics vertical slice** — Done: [scripts/bootstrap_bq.py](scripts/bootstrap_bq.py) + [scripts/README.md](scripts/README.md); [tools/bigquery_tool.py](tools/bigquery_tool.py) read-only SQL guard + caps; [agents/analytics_agent.py](agents/analytics_agent.py); graph **`analytics`** after **`retrieve`** when intent; `/query` includes `analytics_structured`.
- **12. Code agent + E2B** — Done: [e2b/Dockerfile](e2b/Dockerfile); [tools/code_exec_tool.py](tools/code_exec_tool.py) (15s wall, 64KiB combined output, concurrency 2, no egress); [agents/code_agent.py](agents/code_agent.py) (**only** E2B caller); graph **`code_generation`** after **`analytics`** when intent; `/query` includes `code_structured`; [scripts/README.md](scripts/README.md) E2B notes.
- **13. Parallel fan-out & synthesis** — Full multi-agent paths; Langfuse spans end-to-end.
- **14. POST /query hard API** — Rate limit 60/min (Redis-backed slowapi); latency + `session_id` in response; stable 403 JSON for bad session.
- **15. Ingestion API** — Local BackgroundTasks job tracker; prod Cloud Run Job + pollable `job_id` status.
- **16. Observability & dashboards** — Langfuse hosted; Cloud Monitoring dashboard + alerts (spec §11–§12).
- **17. Eval harness** — Golden dataset + RAGAS + DeepEval; nightly/manual; keep PR pytest fast.
- **18. Cloud Build & Run deploy** — Dockerfile, `cloudbuild.yaml`, Secret Manager; `us-central1` API (+ Qdrant if applicable).

## Checkpoint gates (between phases)

From spec: **(a)** auth + session tests green before agents; **(b)** RAG path produces traces before enabling rerank in prod; **(c)** BigQuery bootstrap repeatable before Analytics eval cases; **(d)** E2B template pinned + regression test for sandbox timeouts before broad execution exposure.


| Gate                                | Status |
| ----------------------------------- | ------ |
| (a) Auth + session                  | ☐      |
| (b) RAG traces before prod rerank   | ☐      |
| (c) Repeatable BQ bootstrap         | ☑      |
| (d) E2B pinned + timeout regression | ☑      |


## Notes

*Use for decisions, blockers, or links to PRs. Newest first.*

- Scaffold choices: Python **3.12**, **uv** + pyproject, **Ruff** only, **ADC only** (no SA JSON), **BIGQUERY_DATASET=querymesh**, local **Postgres** user/db **postgres** / **querymesh**, **Langfuse** env empty until §15.16, proprietary **LICENSE**, **no CI** until GitHub remote.
- **Phase 3:** Alembic at repo root; LangGraph DDL aligned with `langgraph-checkpoint-postgres==3.0.5` `MIGRATIONS[0:11]`; non-CONCURRENT indexes for transactional migration.
- **Phase 4:** Bearer auth, `pydantic-settings`, async pool + session scope, `scripts/mint_api_key.py`, `POST /query` stub; 401 JSON matches spec shape pattern.
- **Phase 5:** Redis session envelope (24h TTL), `session_id` / `thread_id` for LangGraph, 403 stable JSON; settings require `REDIS_URL`.
- **Phase 6:** [memory/longterm.py](memory/longterm.py) Postgres read policy + compaction; `/query` loads memory before stub orchestrator; session unit tests monkeypatch DB load to avoid TestClient/asyncpg loop issues.
- **Phase 7:** [graph/pipeline.py](graph/pipeline.py) + [memory/checkpointer.py](memory/checkpointer.py) — LangGraph `StateGraph`, Postgres `AsyncPostgresSaver`, `thread_id` threading; unit tests use `MemorySaver`.
- **Phase 8:** Ingestion (`ingestion/*`), Vertex `text-embedding-004`, Qdrant upsert CLI ([ingestion/indexer.py](ingestion/indexer.py)), [tools/retrieval_tool.py](tools/retrieval_tool.py), graph **`retrieve`** node; `retrieval_hits` on `/query`; `RAG_VERTEX_RERANK` log-only stub.
- **Phase 9:** [agents/orchestrator.py](agents/orchestrator.py) — Gemini routing + fallbacks; graph node `orchestrator`; `orchestrator.source` metadata on `/query`.
- **Phase 10:** RAG JSON ([agents/rag_agent.py](agents/rag_agent.py)), synthesizer ([agents/synthesizer.py](agents/synthesizer.py)), [tools/memory_tool.py](tools/memory_tool.py); graph nodes `rag_structured`, `synthesizer`; shared [agents/vertex.py](agents/vertex.py), [agents/jsonutil.py](agents/jsonutil.py).
- **Phase 11:** BigQuery bootstrap + IAM notes in [scripts/README.md](scripts/README.md); [agents/analytics_agent.py](agents/analytics_agent.py) + [tools/bigquery_tool.py](tools/bigquery_tool.py); graph **`analytics`** after **`retrieve`** when intent; Ruff + pytest green.
- **Phase 12:** [agents/code_agent.py](agents/code_agent.py) + [tools/code_exec_tool.py](tools/code_exec_tool.py); `e2b` dependency; pipeline adds **code_generation** between analytics and RAG; synthesizer + `/query` carry `code_structured`; timeout regression test in [tests/test_code_exec_tool.py](tests/test_code_exec_tool.py).

