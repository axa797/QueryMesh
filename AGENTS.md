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

- **Solo development:** commit directly to **`main`**. Do not create feature branches (including `cursor/*`) unless the user explicitly asks for one.

## How to work in this repo

1. Check **PROGRESS.md** for the current phase; prefer completing the next unchecked §15 item unless fixing bugs.
2. After meaningful progress, update **PROGRESS.md** (check boxes, **Current focus**, **Notes**, or checkpoint table).
3. Prefer small, reviewable commits on **`main`**; match existing layout and tooling.
4. When behavior or API is ambiguous, **cite `spec.md` section** in commit messages or notes rather than inventing requirements.
5. **CI:** none until there is a GitHub remote; add GitHub Actions when you push.

## Files agents should touch

| Purpose | File |
| --- | --- |
| Requirements & architecture | `spec.md` |
| Done / next | `PROGRESS.md` |
| Env template | `.env.example` |
| This context | `AGENTS.md` |
