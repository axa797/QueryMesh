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
6. `POST /ingest` to reload the corpus into Qdrant (when conditions match)

### Step 3b — Deploy Web UI to Cloud Run (optional)

After the API is live, run once from repo root:

```bash
gcloud builds submit --config infra/cloudbuild-web.yaml
```

Or push under `web/` on `main` once the **`web-deploy`** trigger exists ([bootstrap_gcp.sh](../scripts/bootstrap_gcp.sh) creates it for new projects). The build resolves the public **`api`** URL and bakes it into the Next.js bundle.

Set **`CORS_ALLOW_ORIGINS`** on the **`api`** service to include the printed **`web`** URL.

### CORS from Terraform + Google OAuth secrets

- **CORS:** Allowed browser origins for the API are driven by Terraform variables
  **`cors_allow_origins`** and **`cors_allow_origin_regex`** (defaults match the historical
  Vercel example). Override them via **`infra/cloudbuild.tf.yaml`** substitutions
  **`_CORS_ALLOW_ORIGINS`** / **`_CORS_ALLOW_ORIGIN_REGEX`** on the **`tf-apply`** trigger,
  or set `cors_allow_origins` / `cors_allow_origin_regex` in `terraform.tfvars` for local
  `terraform apply`. After changing CORS, run **`tf-apply`** (or push `infra/terraform/**`)
  so **`reconcile-deploy`** refreshes the **`deploy`** trigger’s `_EXTRA_DEPLOY_ARGS`.
- **OAuth:** Create all four optional secrets (**`GOOGLE_OAUTH_CLIENT_ID`**,
  **`GOOGLE_OAUTH_CLIENT_SECRET`**, **`GOOGLE_OAUTH_REDIRECT_URI`**,
  **`PORTAL_FRONTEND_BASE_URL`**) in Secret Manager — **`scripts/bootstrap_gcp.sh`** can
  prompt for them. They must match your Google Cloud Console OAuth client (**authorized
  redirect URIs** = API callback such as `https://<api>/account/oauth/google/callback`;
  **JavaScript origins** = your Next origin). The **`reconcile-deploy`** step binds these
  to the **`api`** Cloud Run service **only when all four secrets exist**; otherwise the
  API still deploys and portal Google sign-in stays disabled (`503 oauth_disabled`).

### Ongoing

| What changed | What to push | Which trigger fires |
|---|---|---|
| App code (not `web/` only) | Changes outside `infra/terraform/**` and `web/**` | `deploy` |
| Web UI only | `web/**` | `web-deploy` |
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
