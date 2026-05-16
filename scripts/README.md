# Scripts

## `bootstrap_gcp.sh` — one-time GCP project setup

Run **once** from [Cloud Shell](https://shell.cloud.google.com) to provision all backing
services and CI/CD triggers. See [infra/README.md](../infra/README.md) for the full deploy flow.

```bash
bash scripts/bootstrap_gcp.sh
```

## `verify_gcp_portal.sh` — portal / OAuth readiness (GCP)

Checks Secret Manager + Cloud Run **`api`** bindings; with **`VERIFY_VALUES=1`** (default) compares redirect URI and frontend URL to production expectations (no secret values printed).

```bash
bash scripts/verify_gcp_portal.sh
VERIFY_HEALTH=1 bash scripts/verify_gcp_portal.sh
EXPECTED_PORTAL_FRONTEND_BASE_URL=https://query-mesh.vercel.app bash scripts/verify_gcp_portal.sh
```

See [infra/README.md](../infra/README.md) (OAuth go-live).

## `sync_gcp_portal_secrets.sh` — sync OAuth redirect + frontend (GCP)

Derives **`GOOGLE_OAUTH_REDIRECT_URI`** from live Cloud Run **`status.url`**; sets **`PORTAL_FRONTEND_BASE_URL`** from **`EXPECTED_PORTAL_FRONTEND_BASE_URL`** (default `https://query-mesh.vercel.app`). **Does not** `source .env`.

```bash
bash scripts/sync_gcp_portal_secrets.sh
```

## `park_gcp_compute.sh` / `wake_gcp_compute.sh` — save GCP compute costs

Scale **api** + **qdrant** to `min-instances=0` and **stop Cloud SQL** (`querymesh-pg`). **Redis** is left running.

```bash
bash scripts/park_gcp_compute.sh
bash scripts/wake_gcp_compute.sh   # SQL first, then Run (one script; not three manual steps)
```

Pause **`deploy`** / **`tf-apply`** Cloud Build triggers if you do not want a git push to wake services.

## `run_gcp_eval.sh` — RAGAS eval → `eval_reports` (GCP)

Submits **`infra/cloudbuild-eval.yaml`**: harvest + RAGAS judge + DB persist. Run after deploy/ingest when **`/eval`** is empty.

```bash
bash scripts/run_gcp_eval.sh
EVAL_LIMIT=5 bash scripts/run_gcp_eval.sh
```

## `check_secrets.sh` — secret scanner

Scans git history and tracked files for accidentally committed credentials. Run before
pushing to a new remote or as part of a security review.

```bash
bash scripts/check_secrets.sh           # warn only
bash scripts/check_secrets.sh --strict  # exit 1 on any finding
```

## `fetch_next26_corpus.py` — corpus refresh

Downloads ~69 Google Cloud Next '26 documentation pages into `corpus/gcp_docs/` for RAG
ingestion. Use `--clean` to replace the existing corpus entirely.

```bash
PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py --clean
```

See [docs/corpus_runbook.md](../docs/corpus_runbook.md) for the full refresh workflow
(fetch → drop Qdrant collection → ingest → harvest evals).

## `mint_api_key.py` — issue API keys

Mints a raw API key, stores its HMAC-SHA256 digest in Postgres, and prints the key once.
Requires `DATABASE_URL` and `API_KEY_PEPPER` to be set.

```bash
PYTHONPATH=. uv run python scripts/mint_api_key.py
```

## `prepare_local.sh` — local dev setup

Starts Postgres, Redis, Qdrant, and the Next.js **web** container via Docker Compose; creates `corpus/gcp_docs`. See [docs/local_dev.md](../docs/local_dev.md).

```bash
bash scripts/prepare_local.sh
```

## BigQuery — analytics agent IAM

The analytics agent uses `BIGQUERY_PROJECT_ID` / `BIGQUERY_DATASET` to run read-only
queries. Grant the Cloud Run service account (set up by `bootstrap_gcp.sh`):

- `roles/bigquery.jobUser` — on the project
- `roles/bigquery.dataViewer` — on the `querymesh` dataset

Bootstrap the `doc_metadata` table once via the BigQuery console or `bq` CLI if the
analytics agent's sample queries require it.
