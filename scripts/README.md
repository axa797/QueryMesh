# Scripts

## `mint_api_key.py`

Issue API keys (see [AGENTS.md](../AGENTS.md) Development section).

## HTTP ingestion API (`POST /ingest`, Phase 15)

From a running API, with `INGESTION_GCP_DOCS_DIR` pointing at your document tree and Qdrant + Vertex available:

```bash
curl -sS -X POST "http://localhost:8000/ingest" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source":"gcp_docs"}'
# Poll: GET /ingest/{job_id} with the same Authorization header.
```

**Corpus layout, PDF sourcing, and reindexing:** [docs/corpus_runbook.md](../docs/corpus_runbook.md).

CLI alternative: `PYTHONPATH=. uv run python -m ingestion.indexer --source /path/to/docs --google-cloud-project YOUR_PROJECT_ID`.

## `bootstrap_bq.py` — synthetic BigQuery doc metadata (spec §6.4)

**Prereqs:** [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) (`gcloud auth application-default login`). **Do not** rely on committed service account JSON.

**Run (from repo root):**

```bash
PYTHONPATH=. uv run python scripts/bootstrap_bq.py --project YOUR_PROJECT_ID
```

Optional: `--dataset querymesh` (default), `--location US`, `--force` to truncate and reseed.

Creates `YOUR_PROJECT_ID.querymesh.doc_metadata` with columns `doc_name`, `section`, `word_count`, `last_updated`, `product_area`, and inserts a small deterministic seed if the table is empty.

### IAM (least privilege for the **API** workload)

Grant the Cloud Run / API service account (not end users):

- **`roles/bigquery.jobUser`** on the project (or a custom role that includes `bigquery.jobs.create`), so queries can run.
- **`roles/bigquery.dataViewer`** on dataset `querymesh` (tighter than project-wide), so `SELECT` on `doc_metadata` works.

The human running **bootstrap** once needs broader rights (e.g. `bigquery.admin` or editor on the dataset) to create the dataset and table.

### Env vars

- `BIGQUERY_PROJECT_ID` — often same as `GOOGLE_CLOUD_PROJECT`
- `BIGQUERY_DATASET` — default `querymesh`
- `BIGQUERY_LOCATION` — dataset location for bootstrap (default `US` in the script)

## E2B — code execution sandbox (spec §6.3, Phase 12)

**Prereqs:** E2B account + API key; custom template built from [e2b/Dockerfile](../e2b/Dockerfile) (Python + `google-cloud-*` wheels, **no ADC** baked in). Build/publish with the [E2B template CLI](https://e2b.dev/docs/template/quickstart); set **`E2B_TEMPLATE_ID`** to the template name or ID you deployed (default in code: `querymesh-code`).

**Runtime env (API):**

- `E2B_API_KEY` — required to run user code in the sandbox.
- Optional tuning: see `code_exec_*` and `e2b_*` fields in [api/settings.py](../api/settings.py) (15s command wall, 64KiB combined stdout/stderr cap, max 2 concurrent executions per process).

Sandboxes are created with **`allow_internet_access=False`**. The API must not inject GCP credentials into the sandbox environment.
