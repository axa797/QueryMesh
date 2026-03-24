#!/usr/bin/env python3
"""Create BigQuery dataset + synthetic doc metadata table (spec §6.4, §15.11).

Uses Application Default Credentials. Idempotent: creates dataset/table if missing;
seeds rows only when the table is empty (use --force to truncate and reseed).

Example:
  PYTHONPATH=. uv run python scripts/bootstrap_bq.py --project YOUR_GCP_PROJECT

See scripts/README.md for IAM notes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_TABLE = "doc_metadata"

SEED_ROWS: list[dict[str, object]] = [
    {
        "doc_name": "cloud-run-overview.pdf",
        "section": "Scaling",
        "word_count": 4200,
        "last_updated": "2025-06-01",
        "product_area": "Cloud Run",
    },
    {
        "doc_name": "bigquery-sql-reference.pdf",
        "section": "Standard SQL",
        "word_count": 18500,
        "last_updated": "2025-04-15",
        "product_area": "BigQuery",
    },
    {
        "doc_name": "gke-autoscaling.pdf",
        "section": "Horizontal Pod Autoscaler",
        "word_count": 9100,
        "last_updated": "2025-01-20",
        "product_area": "GKE",
    },
    {
        "doc_name": "cloud-storage-buckets.pdf",
        "section": "Lifecycle",
        "word_count": 5300,
        "last_updated": "2025-03-10",
        "product_area": "Cloud Storage",
    },
    {
        "doc_name": "vertex-ai-models.pdf",
        "section": "Endpoints",
        "word_count": 6700,
        "last_updated": "2025-05-22",
        "product_area": "Vertex AI",
    },
    {
        "doc_name": "cloud-run-overview.pdf",
        "section": "Networking",
        "word_count": 3800,
        "last_updated": "2025-06-01",
        "product_area": "Cloud Run",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap BigQuery synthetic doc metadata.")
    parser.add_argument(
        "--project",
        default=os.environ.get("BIGQUERY_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="GCP project id (default: BIGQUERY_PROJECT_ID or GOOGLE_CLOUD_PROJECT).",
    )
    parser.add_argument(
        "--dataset",
        default=os.environ.get("BIGQUERY_DATASET", "querymesh"),
        help="Dataset id (default: env BIGQUERY_DATASET or querymesh).",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("BIGQUERY_LOCATION", "US"),
        help="Dataset location (default US; use us-central1 multi-align if your org requires).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate doc_metadata and reseed (destructive).",
    )
    args = parser.parse_args()
    if not args.project:
        print(
            "error: pass --project or set BIGQUERY_PROJECT_ID / GOOGLE_CLOUD_PROJECT",
            file=sys.stderr,
        )
        return 1

    os.environ.setdefault("PYTHONPATH", str(ROOT))

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project)

    ds_ref = f"{args.project}.{args.dataset}"
    try:
        client.get_dataset(ds_ref)
        print(f"dataset exists: {ds_ref}")
    except Exception:
        ds = bigquery.Dataset(ds_ref)
        ds.location = args.location
        client.create_dataset(ds, exists_ok=True)
        print(f"created dataset: {ds_ref} ({args.location})")

    table_ref = f"{ds_ref}.{DOC_TABLE}"
    schema = [
        bigquery.SchemaField("doc_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("section", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("word_count", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("last_updated", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("product_area", "STRING", mode="REQUIRED"),
    ]
    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table, exists_ok=True)
    print(f"table ready: {table_ref}")

    if args.force:
        client.query(f"TRUNCATE TABLE `{table_ref}`").result()
        print("truncated table (--force)")

    cnt_job = client.query(f"SELECT COUNT(1) AS c FROM `{table_ref}`")
    n = list(cnt_job.result())[0]["c"]
    if n == 0:
        errors = client.insert_rows_json(table_ref, SEED_ROWS)
        if errors:
            print("insert_rows_json errors:", errors, file=sys.stderr)
            return 1
        print(f"seeded {len(SEED_ROWS)} row(s) into {table_ref}")
    else:
        print(f"table already has {n} row(s); skip seed (use --force to reseed)")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
