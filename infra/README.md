# Infrastructure

## Local development

Docker Compose brings up Postgres, Redis, and Qdrant:

```bash
docker compose -f infra/docker-compose.yml up -d
```

See [docs/local_dev.md](../docs/local_dev.md) for the full local setup walkthrough.

---

## Production deployment (GCP — us-central1)

Everything is automated. No manual `gcloud` commands required after the one-time bootstrap.

### Step 1 — Bootstrap (run once from Cloud Shell)

Open [Cloud Shell](https://shell.cloud.google.com), clone the repo, and run:

```bash
bash scripts/bootstrap_gcp.sh
```

This enables all required APIs, creates the GCS Terraform state bucket, Artifact Registry,
Secret Manager secrets (you are prompted for each value), IAM bindings, and Cloud Build
triggers connected to your GitHub repo.

The only manual step is a single OAuth click to authorize the Cloud Build GitHub App —
the script prints the URL.

### Step 2 — Provision backing services (automatic on push)

Push any change under `infra/terraform/` to `main`. The `tf-apply` Cloud Build trigger
fires automatically and runs [infra/cloudbuild.tf.yaml](cloudbuild.tf.yaml):

```
terraform init → validate → plan → apply → reconcile-deploy
```

This provisions: Cloud SQL (Postgres 16), Memorystore (Redis 7), Qdrant on Cloud Run
(`min-instances=1`), and the VPC connector. State lives in
`gs://${PROJECT_ID}-tf-state/terraform/state`.

The final `reconcile-deploy` step is what makes the setup truly zero-manual-step:

1. Reads terraform outputs (Cloud SQL connection name, Redis host/port, Qdrant URL,
   VPC connector).
2. Writes fresh versions of three derived secrets — `DATABASE_URL`, `REDIS_URL`,
   `QDRANT_URL` — so they always reflect the current infrastructure. The secret
   *schemas* are managed in [terraform/secrets.tf](terraform/secrets.tf); their
   *values* are composed from other secrets + outputs inside the build.
3. Updates the `deploy` trigger's `_EXTRA_DEPLOY_ARGS` substitution so every future
   push to `main` deploys with the correct Cloud SQL attachment, VPC connector, and
   secret bindings — no `gcloud ... --update-substitutions` command to remember.

The step is idempotent: if values are unchanged, it's a no-op. If SQL or Redis are
ever recreated (restore from backup, region move, etc.), the next `tf-apply`
automatically re-points everything.

### Step 3 — Deploy API (automatic on push)

Push any app code change to `main`. The `deploy` Cloud Build trigger fires and runs
[infra/cloudbuild.yaml](cloudbuild.yaml):

1. Build and tag the Docker image
2. Scan image layers for accidentally baked-in secrets
3. Push to Artifact Registry
4. Run `alembic upgrade head` via Cloud SQL Auth Proxy sidecar
5. `gcloud run deploy api` (with the flag blob reconciled by `tf-apply`)
6. `POST /ingest` to reload the corpus into Qdrant

### Ongoing

| What changed | What to push | Which trigger fires |
|---|---|---|
| App code | Anything outside `infra/terraform/` | `deploy` |
| Infrastructure | `infra/terraform/**` | `tf-apply` |
| PR opened / updated | Any branch | GitHub Actions (lint + pytest) |

---

## Terraform module

| File | Manages |
|---|---|
| `terraform/main.tf` | Provider, GCS backend |
| `terraform/apis.tf` | Required GCP APIs |
| `terraform/network.tf` | VPC Serverless Access connector |
| `terraform/sql.tf` | Cloud SQL Postgres 16 |
| `terraform/redis.tf` | Memorystore Redis 7 |
| `terraform/qdrant.tf` | Cloud Run Qdrant service |
| `terraform/iam.tf` | Cloud Build SA + Cloud Run SA roles |
| `terraform/outputs.tf` | Connection names, URLs, deploy command |

Secret _values_ are never stored in Terraform state — they are written to Secret Manager
by `scripts/bootstrap_gcp.sh` and referenced by name only.

---

## Further reading

- [docs/production_infra.md](../docs/production_infra.md) — detailed breakdown of each
  backing service (Cloud SQL config, VPC connector, Qdrant persistence notes)
- [docs/cloud_logging_metrics.md](../docs/cloud_logging_metrics.md) — log-based metrics
  and alert policy setup
- [scripts/bootstrap_gcp.sh](../scripts/bootstrap_gcp.sh) — annotated bootstrap source
