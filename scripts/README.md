# Scripts

## `mint_api_key.py`

Issue API keys (see [AGENTS.md](../AGENTS.md) Development section).

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
