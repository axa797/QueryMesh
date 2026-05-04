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

**Optional — browser signup (same DB tables):** set **`PORTAL_JWT_SECRET`** in `.env` (see `.env.example`). Then use `POST /account/register` and `POST /account/login` for a portal JWT, and `POST /account/api-keys` (Bearer that JWT) to mint a raw key for **`POST /query`**.

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

**Alternatively — Next.js UI:** from [web/README.md](../web/README.md): `cd web && cp .env.example .env.local && npm install && npm run dev` → [http://localhost:3000](http://localhost:3000). Or Docker: `docker compose -f infra/docker-compose.yml up -d --build web` (API URL baked at image build; default targets `http://127.0.0.1:8000`). Register/login, mint keys, and chat against `POST /query`. The API needs **`PORTAL_JWT_SECRET`** and `CORS_ALLOW_ORIGINS` including `http://localhost:3000` (or `*` locally).

## 5. RAG corpus (optional)

Without indexed PDFs, retrieval is empty; orchestrator/synthesizer may still run if `GOOGLE_CLOUD_PROJECT` is set.

- Put public GCP-doc PDFs under `./corpus/gcp_docs/` (see [corpus_runbook.md](corpus_runbook.md)).
- Set `INGESTION_GCP_DOCS_DIR=./corpus/gcp_docs` and `GOOGLE_CLOUD_PROJECT` in `.env`.
- Run `POST /ingest` with `{"source":"gcp_docs"}` — see [docs/corpus_runbook.md](corpus_runbook.md) for the full workflow.

## 6. Tests (same as CI)

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/querymesh
export API_KEY_PEPPER=local-dev-pepper
export REDIS_URL=redis://127.0.0.1:6379/0
export RATE_LIMIT_STORAGE_URI=memory://
uv run pytest -q
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
