# querymesh — implementation progress

Single source of truth for **what is done** vs **spec §15 build order**.  
Update this file when starting or finishing a phase (short note under the item is enough).

**Spec:** [spec.md](spec.md)  
**Agent context:** [AGENTS.md](AGENTS.md)

## Current focus

- **Phase 3** — Postgres schema & migrations (next).

## Phase checklist (§15)

- **1. Repo scaffold** — Done: Python 3.12, uv, [pyproject.toml](pyproject.toml), Ruff, package layout per spec, [.env.example](.env.example), [LICENSE](LICENSE), [tests/test_health.py](tests/test_health.py). Dependencies in `pyproject.toml` only (no `requirements.txt`).
- **2. Infra primitives (local)** — Done: [infra/docker-compose.yml](infra/docker-compose.yml) — Qdrant, Redis, Postgres (`postgres` / `querymesh`); Langfuse vars in [.env.example](.env.example) empty until observability (§15.16).
- **3. Postgres schema & migrations** — `users`, `api_keys`, `user_memory`, LangGraph checkpointer tables; constraints (`CHECK memory_type`), indexes.
- **4. Auth middleware** — Bearer → digest → `user_internal_id`; constant-time compare; CLI or script to mint keys + `users` row.
- **5. Session layer** — Redis envelope + bind/mint `session_id`; 403 on mismatch; composite `thread_id` for LangGraph.
- **6. Long-term memory reads** — Top-k loader + 256-token compaction + ordering; wire before orchestrator.
- **7. LangGraph skeleton** — Stateful graph + checkpointer; single-path echo → orchestrator stub.
- **8. RAG vertical slice** — Ingestion CLI (`loader`/`chunker`/`indexer`), Qdrant collection, retrieval node; rerank flag off locally by default.
- **9. Orchestrator** — Structured routing JSON + retry → RAG fallback; fan-out ≤ 3; temperatures per spec.
- **10. Synthesizer** — Render structured RAG JSON; `save_memory` tool **only** here.
- **11. Analytics vertical slice** — `scripts/bootstrap_bq.py` + README; IAM least privilege; analytics agent + guarded SQL.
- **12. Code agent + E2B** — Python template, no egress, baked `google-cloud-`*; `code_exec_tool`; caps 15s, 64KiB stdout/stderr, 2 concurrent/replica.
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
| (c) Repeatable BQ bootstrap         | ☐      |
| (d) E2B pinned + timeout regression | ☐      |


## Notes

*Use for decisions, blockers, or links to PRs. Newest first.*

- Scaffold choices: Python **3.12**, **uv** + pyproject, **Ruff** only, **ADC only** (no SA JSON), **BIGQUERY_DATASET=querymesh**, local **Postgres** user/db **postgres** / **querymesh**, **Langfuse** env empty until §15.16, proprietary **LICENSE**, **no CI** until GitHub remote.