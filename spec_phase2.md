# querymesh — Phase 2 specification (“bring it to life”)

This document **extends** [spec.md](spec.md). It does not redefine non‑negotiables from the base spec (auth, sessions, memory write policy, fan-out cap, region, E2B constraints). **Authoritative v1 technical detail remains in `spec.md`.**

**Inventory of what is already built:** See [PROGRESS.md](PROGRESS.md). At a high level, Phase 1 delivered the full §15 build order: FastAPI API, Postgres + Alembic + LangGraph checkpointer, Redis sessions and rate limits, RAG (ingestion + Qdrant + retrieval), orchestrator + synthesizer + long-term memory, BigQuery analytics path, E2B code path with parallel specialists, Langfuse hooks, ingest API (local in-process jobs), eval harness, and Cloud Build / Cloud Run deploy artifacts.

Phase 2 turns that implementation into something **dependable, observable, and usable by humans**—closing gaps between “code exists” and “product behaves like the spec promises in production.”

---

## 1. North star

A teammate or stakeholder can:

1. Open a **documented entrypoint** (web demo and/or guided CLI), run a query, and see citations + trace id without reading the repo.
2. Trust **production** ingestion (restart-safe jobs, pollable status) and **retrieval quality** (real rerank behind `RAG_VERTEX_RERANK`, not only logging).
3. See **SLO-oriented signals** in Cloud Monitoring (not only constant stubs) and fail the build or deploy when **core gates** regress.
4. Run **CI** on every change: fast tests on PR, optional scheduled evals, deploy on `main` where Cloud Build is wired.

---

## 2. Gap analysis (Phase 1 → Phase 2)


| Area                        | Phase 1 state                                                                                 | Phase 2 target                                                                                                                                                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reranking                   | `RAG_VERTEX_RERANK` honored as **log-only stub**                                              | When flag on: **Vertex rerank** (or documented equivalent) applied to retrieval candidates before RAG JSON; metrics for rerank latency and skip rate                                                      |
| Ingestion in prod           | `job_id` state **in-process** (single worker); spec calls for **Cloud Run Job** + persistence | Persisted job store (Postgres or Redis), API triggers job or delegate worker; survives replica restart; same poll contract as today                                                                       |
| Checkpoint gates            | [PROGRESS.md](PROGRESS.md) gate **(a)** auth + session tests still open                       | Green, stable tests for Bearer → user, session mint/403, `thread_id` composition                                                                                                                          |
| Cloud Monitoring            | [observability/gcp_monitoring.py](observability/gcp_monitoring.py) names/constants **stubs**  | At least one **exported metric** or log-based metric filter wired from hot path (e.g. `/query` latency, error flag); README dash setup                                                                    |
| “Dashboard live” (spec §14) | Partially met via Langfuse; GCP dashboard optional                                            | Terraform or click-path doc + one confirmed chart fed by prod logs/metrics                                                                                                                                |
| CI                          | No GitHub Actions until remote exists (per AGENTS)                                            | Add **GitHub Actions** (or document Cloud Build PR trigger only): lint + fast pytest on PR; optional `workflow_dispatch` nightly eval                                                                     |
| Human-facing surface        | API-only                                                                                      | Thin **demo UI** or **Typer CLI** in repo: `BASE_URL` + API key, session carry-over, shows `message` + trace link pattern                                                                                 |
| Corpus scale                | Implementation supports corpus; §9 target 15–20 PDFs                                          | Scripted or documented **corpus refresh** approaching page budget; ingestion runbook                                                                                                                      |
| Base spec drift             | spec §13 still mentions `pip` / `requirements.txt`                                            | **Do not edit `spec.md` in Phase 2 unless you explicitly reconcile**; Phase 2 acceptance includes a **short “developer path”** section here that points at `uv`, [AGENTS.md](AGENTS.md), and Docker-first |


---

## 3. Workstreams

### 3.1 Production ingestion and jobs

**Goal:** `POST /ingest` and `GET /ingest/{job_id}` behave the same locally and in Cloud Run from the client’s perspective, but prod does not lose jobs on deploy.

**Requirements:**

- Persist `job_id` status transitions (`queued` / `running` / `complete` / `failed`), `docs_indexed`, error message, `created_at` / `updated_at`.
- API may enqueue work via Cloud Run Job execution **or** a dedicated worker service; choose one and document in [infra/README.md](infra/README.md).
- Idempotent or clearly documented behavior if the same source is ingested twice (recreate vs append).

**Acceptance:** Restart API pod/replica during a long ingest; poll resumes correctly; no duplicate “complete” without an actual run.

### 3.2 Retrieval quality (rerank)

**Goal:** Honor `RAG_VERTEX_RERANK` as a real retrieval stage when enabled.

**Requirements:**

- Define ordering: embed search → (optional) rerank top-N → trim to top-k for RAG agent.
- Log rerank failures gracefully; fall back to dense order and increment a **skip/fallback** counter.
- Feature flag defaults unchanged vs base spec (prod on, local off).

**Acceptance:** With flag on in a project with Vertex enabled, integration or smoke test asserts order differs from pure vector order on a fixed fixture **or** asserts rerank API was invoked (contract test with mocked Vertex).

### 3.3 Quality gates and CI

**Goal:** regressions in auth/session and core graph contract are caught automatically.

**Requirements:**

- Close PROGRESS gate **(a)**: pytest coverage for minted vs invalid `session_id`, stable 403 JSON, and rate limit exempt `/health` unchanged.
- PR pipeline: `ruff check`, `ruff format --check`, fast `pytest` (exclude `eval` marker per [pyproject.toml](pyproject.toml)).
- Optional: scheduled workflow with `RUN_EVAL=1` on golden subset (cost-controlled).

**Acceptance:** Green CI on a clean clone using documented secrets-only-for-external-keys pattern.

### 3.4 Observability that operators use

**Goal:** Someone on call can answer “is the system slow or broken?” without opening Langfuse for every incident.

**Requirements:**

- Emit structured logs or metrics for: `/query` outcome (success vs 4xx/5xx class), coarse intent bucket (from orchestrator output if available), and wall time.
- Document alert wiring: at minimum link §11 thresholds to a log-based metric or Cloud Monitoring MQL in [infra/README.md](infra/README.md).

**Acceptance:** Screenshot or exported chart not required in-repo; **written proof** (link or paste JSON filter) that prod or staging feeds one dashboard tile.

### 3.5 Product surface (“alive”)

Pick **at least one** (both allowed):

- **Demo web app** (static or minimal framework): input box, streaming optional, displays assistant `message`, `trace_id`, `session_id`; reads API base URL and key from env; no server-side storage of secrets.
- **CLI** (`uv run python -m …`): same fields, supports `session_id` file in user cache dir.

**Requirements:**

- Uses only public API (`Authorization: Bearer`, `POST /query`); no trust of client-supplied user id.
- README entry: how to point at local Docker stack vs Cloud Run URL.

**Acceptance:** A new user follows only Phase 2 README slice + `.env.example` vars and gets a successful answer with trace id.

### 3.6 Corpus and eval discipline

**Goal:** Evals measure something representative of prod retrieval.

**Requirements:**

- Document corpus location, approximate size, and how to re-run ingestion after PDF drop.
- Tie at least **one** golden case to analytics + one to code path (already in dataset—verify they fail loudly if tools are mis-wired).

optional **Stretch:** block merge if RAGAS faithfulness on a tiny fixed subset drops below a floor ( flaky metrics → tune threshold carefully).

---

## 4. Phase 2 build order

Recommended sequence to reduce thrash:

1. **CI skeleton** — GitHub Actions (or documented Cloud Build PR-only) for Ruff + fast pytest.
2. **Gate (a) tests** — Auth + session + thread_id invariants.
3. **Rerank implementation** — Behind `RAG_VERTEX_RERANK`, with tests.
4. **Ingestion persistence + prod job path** — Schema migration if Postgres-backed; worker contract.
5. **Observability wiring** — Logs/metrics + README for dashboard.
6. **Demo UI or CLI** — Polish enough for a external demo.
7. **Corpus runbook** — Ingest at scale; snapshot eval numbers in PROGRESS or internal doc.

Dependencies: (3) may run in parallel with (2) after CI exists; (4) is orthogonal to (3) but should land before betting on prod demos.

---

## 5. Success criteria (Phase 2)


| Criterion        | Measure                                                                    |
| ---------------- | -------------------------------------------------------------------------- |
| Demo path        | Non-developer can run sample query via UI or CLI using only docs + API key |
| Prod ingestion   | Job survives API restart; status monotonic; failure surfaced in GET        |
| Rerank           | Flag-on path calls real rerank or documented fallback with metrics         |
| CI               | PRs mandatory green for lint + fast tests                                  |
| Ops              | At least one GCP Monitoring or log-based chart tied to `/query` health     |
| Regression guard | Gate (a) checked in PROGRESS                                               |


---

## 6. Non-goals (defer)

- Self-hosted Langfuse on Cloud Run (base spec defers).
- Multi-region active-active.
- MCP servers exposed externally (keep internal registry only).
- Replacing HMAC API keys with OAuth (unless a separate security initiative).

---

## 7. Developer path (Phase 2 canonical)

Aligned with [AGENTS.md](AGENTS.md): **Python 3.12**, **uv** + [pyproject.toml](pyproject.toml), **Ruff**, **ADC** for GCP, **Docker-first** local dependencies via [infra/docker-compose.yml](infra/docker-compose.yml). Copy [.env.example](.env.example) to `.env`; do not commit secrets.

For Phase 2 feature work, prefer commands run **inside** the dev container or `docker compose run` targets as those targets are added—avoid baking “host `pip install`” into new docs.

---

## 8. Traceability


| This doc           | Touches (examples)                                                                                                               |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| ingest persistence | [api/routes/ingest.py](api/routes/ingest.py), [api/ingestion_jobs.py](api/ingestion_jobs.py), [infra/README.md](infra/README.md) |
| rerank             | [tools/retrieval_tool.py](tools/retrieval_tool.py), [api/settings.py](api/settings.py)                                           |
| gates / CI         | [tests/](tests/), [.github/workflows/](.github/workflows/) (new)                                                                 |
| demo               | new `demo/` or `clients/` subtree (TBD)                                                                                          |
| metrics            | [observability/gcp_monitoring.py](observability/gcp_monitoring.py), [api/routes/query.py](api/routes/query.py)                   |


When a Phase 2 milestone completes, update [PROGRESS.md](PROGRESS.md) with a dated note under **Notes** and, if appropriate, a **Phase 2** subsection so the single “what’s done” file stays honest.