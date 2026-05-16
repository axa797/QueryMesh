# Local development (before Cloud Run)

Run the API on your machine with Docker-backed Postgres, Redis, and Qdrant—no GCP deploy required. Vertex AI and BigQuery only matter when you want full RAG, orchestrator, analytics, or ingest with embeddings.

## 1. Prerequisites

- Python **3.12** and **[uv](https://docs.astral.sh/uv/)**
- **Docker** (for `infra/docker-compose.yml`)
- Optional for **Gemini / embeddings / rerank**: `gcloud auth application-default login` and a `GOOGLE_CLOUD_PROJECT` in `.env`

## 2. One-time setup

From the repo root:

```bash
./scripts/prepare_local.sh
cp .env.example .env
# Edit .env: set API_KEY_PEPPER (any long random string), GOOGLE_CLOUD_PROJECT if using Vertex.
# For the browser demo, uncomment CORS_ALLOW_ORIGINS=* at the bottom of .env.

uv sync
uv run --env-file .env alembic upgrade head
PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py
```

Save the printed API key; it is shown once.

**Optional — browser signup (same DB tables):** set **`PORTAL_JWT_SECRET`**, **`PORTAL_FRONTEND_BASE_URL`**, **`GOOGLE_OAUTH_CLIENT_ID`**, **`GOOGLE_OAUTH_CLIENT_SECRET`**, and **`GOOGLE_OAUTH_REDIRECT_URI`** in `.env` (see `.env.example`). Configure a Google OAuth Web client whose authorized redirect URI matches **`GOOGLE_OAUTH_REDIRECT_URI`** (for local API host: `http://127.0.0.1:8000/account/oauth/google/callback` or matching `localhost`). The Next app uses **Continue with Google** (full-page navigation to the API); after OAuth it receives the portal JWT in the URL fragment and can call **`POST /account/api-keys`** (Bearer that JWT) to mint a raw key for **`POST /query`**.

Legacy password-only rows in `users` are linked automatically when the verified Google **`email`** matches; **`password_hash`** is cleared on first Google login for that row.

## 3. Run the API

```bash
PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Sanity check:

```bash
curl -s http://127.0.0.1:8000/health | jq .
```

All of `postgres`, `redis`, and `qdrant` should be `true` once compose is up. If `postgres` is false, run `uv run alembic upgrade head` and confirm `DATABASE_URL` matches compose (`postgresql+asyncpg://postgres:postgres@localhost:5432/querymesh`).

## 4. Browser demo

1. Open [demo/querymesh-demo.html](../demo/querymesh-demo.html) (double-click or serve with `python -m http.server` from `demo/`).
2. Set `BASE_URL` to `http://127.0.0.1:8000` and `API_KEY` to the key from `mint_api_key.py`.
3. Ensure the API process has `CORS_ALLOW_ORIGINS=*` (or your page origin) in `.env`.

**Alternatively — Next.js UI (Docker — default):** `docker compose -f infra/docker-compose.yml up -d` from the repo root (see [`web/README.md`](../web/README.md)) → [http://localhost:3000](http://localhost:3000). Use `docker compose ... up -d --build web` after editing **`infra/docker-compose.yml`** `web.build.args` or `web/Dockerfile`. **`NEXT_PUBLIC_QUERYMESH_URL`** must point at the browser-reachable API. The API needs **`PORTAL_JWT_SECRET`**, the Google OAuth vars, **`PORTAL_FRONTEND_BASE_URL`** matching how you open Next (often `http://localhost:3000`), and **`CORS_ALLOW_ORIGINS`** including that origin (or `*` locally).

**Optional:** `cd web && npm run dev` only if actively editing frontend without rebuilding the image.

## 5. RAG corpus (optional)

Without indexed PDFs, retrieval is empty; orchestrator/synthesizer may still run if `GOOGLE_CLOUD_PROJECT` is set.

- Put public GCP-doc PDFs under `./corpus/gcp_docs/` (see [corpus_runbook.md](corpus_runbook.md)).
- Set `INGESTION_GCP_DOCS_DIR=./corpus/gcp_docs` and `GOOGLE_CLOUD_PROJECT` in `.env`.
- Run `POST /ingest` with `{"source":"gcp_docs"}` — see [docs/corpus_runbook.md](corpus_runbook.md) for the full workflow.

## 6. Tests (same as CI)

Start backing services first so `/health`-style checks and anything touching sessions see real infra:

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis qdrant
```

CI does not start Docker for you locally; **`tests/test_health.py`** expects **postgres, redis, and qdrant** reachable when those env vars point at Compose:

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/querymesh
export API_KEY_PEPPER=local-dev-pepper
export REDIS_URL=redis://127.0.0.1:6379/0
export QDRANT_URL=http://127.0.0.1:6333
export RATE_LIMIT_STORAGE_URI=memory://
uv run pytest -q
```

Smoke just dependencies + `/health`:

```bash
uv run pytest tests/test_health.py -v
```

## 7. What still uses GCP locally

| Feature              | Needs GCP / ADC |
| -------------------- | --------------- |
| `/health`            | No              |
| `POST /query` stub-ish paths | Depends: Vertex for orchestrator/RAG agent when project set; see code offline fallbacks |
| Ingest embeddings    | Yes (`GOOGLE_CLOUD_PROJECT`) |
| `RAG_VERTEX_RERANK`  | Yes (Discovery Engine) |
| Analytics agent      | Yes (BigQuery + bootstrap) |
| Code agent + E2B     | E2B API key, not GCP |

If the GCP console stays empty, you are either not calling those APIs yet or only running locally against Docker.
