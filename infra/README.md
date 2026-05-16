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

### Step 3b — Deploy Web UI to Cloud Run (optional, rare)

Use this **only** if you host the Next app on GCP instead of Vercel. Default **`bootstrap_gcp.sh`** does **not** create a **`web-deploy`** trigger (`QUERYMESH_ENABLE_CLOUD_RUN_WEB=1` opt-in). Run once from repo root:

```bash
gcloud builds submit --config infra/cloudbuild-web.yaml
```

Set **`CORS_ALLOW_ORIGINS`** on the **`api`** service to include the printed **`web`** URL when using Cloud Run UI.

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

### OAuth go-live (portal + Google Sign-In)

End-to-end checklist (all must be true for **`oauth_disabled`** to disappear):

1. **Secret Manager** — Non-empty versions for **`PORTAL_JWT_SECRET`** plus all four OAuth secrets: **`GOOGLE_OAUTH_CLIENT_ID`**, **`GOOGLE_OAUTH_CLIENT_SECRET`**, **`GOOGLE_OAUTH_REDIRECT_URI`**, **`PORTAL_FRONTEND_BASE_URL`**. Use **`scripts/bootstrap_gcp.sh`** prompts for first-time setup.
2. **`tf-apply`** — Run the **`tf-apply`** Cloud Build trigger (e.g. push `infra/terraform/**` to `main`) so **`reconcile-deploy`** PATCHes the **`deploy`** trigger’s **`_EXTRA_DEPLOY_ARGS`** with OAuth `--set-secrets` bindings.
3. **Redeploy `api`** — Trigger the **`deploy`** pipeline (app code push to `main`, or manual `gcloud builds submit --config infra/cloudbuild.yaml`) so Cloud Run picks up new secret bindings.
4. **Google Cloud Console** — In **APIs & Services → Credentials → OAuth 2.0 Client (Web)**: **Authorized redirect URIs** must include exactly  
   `https://<your-api-run-url>/account/oauth/google/callback`  
   (same string as **`GOOGLE_OAUTH_REDIRECT_URI`**). **Authorized JavaScript origins** must include your **Vercel** site origin.  
   **Sign-in branding:** On **OAuth consent screen**, set **App name** to `QueryMesh` (and logo / support email). Google’s “Sign in to continue to …” line often shows the **redirect URI host** (`*.run.app`) because the callback is on the API, not the Vercel UI — that is expected unless you use a **custom domain** on Cloud Run or change the OAuth architecture. The large title can still show **QueryMesh** when the consent screen app name is set.
5. **Vercel** — **`NEXT_PUBLIC_QUERYMESH_URL`** = public **`api`** URL; redeploy the frontend after changing it (build-time).

**Anti-pattern:** Do **not** populate production Secret Manager OAuth values by `source .env` from a laptop (local `.env` often has `PORTAL_FRONTEND_BASE_URL=http://localhost:3000` and `GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/...`, which causes Google sign-in to succeed then redirect to localhost).

**Sync derived prod secrets** (redirect URI from live Cloud Run `status.url`, frontend from env var — never reads `.env`):

```bash
bash scripts/sync_gcp_portal_secrets.sh
# EXPECTED_PORTAL_FRONTEND_BASE_URL=https://query-mesh.vercel.app  # default
```

| Setting | Local (`.env`) | Production (Secret Manager / Vercel) |
|--------|----------------|--------------------------------------|
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://127.0.0.1:8000/account/oauth/google/callback` | `https://<api-status-url>/account/oauth/google/callback` |
| `PORTAL_FRONTEND_BASE_URL` | `http://localhost:3000` | `https://query-mesh.vercel.app` (no trailing slash) |
| `NEXT_PUBLIC_QUERYMESH_URL` | `http://127.0.0.1:8000` (Vercel/local build) | Public Cloud Run **`api`** URL (Vercel env, build-time) |
| `CORS_ALLOW_ORIGINS` | `*` or `http://localhost:3000` | `https://query-mesh.vercel.app` (+ regex for `*.vercel.app` previews) |

**Verify** (requires `gcloud` + `jq`, e.g. Cloud Shell):

```bash
bash scripts/verify_gcp_portal.sh              # VERIFY_VALUES=1 by default
VERIFY_HEALTH=1 bash scripts/verify_gcp_portal.sh   # also GET /health (+ origin checks when API is deployed)
```

After API deploy, **`GET /health`** includes non-secret **`capabilities.portal_frontend_origin`** and **`oauth_redirect_origin`** for quick drift checks.

### Eval reports in production (`/eval` UI)

The Vercel **`/eval`** page lists rows from Postgres **`eval_reports`** via **`GET /eval-reports`**. An empty list is normal until a RAGAS run is **persisted** (Alembic revision **`005_eval_reports_table`** is applied on every **`deploy`** migrate step).

**Populate prod data** (after corpus ingest; uses Vertex judge LLM — cost + ~10–20 min):

```bash
bash scripts/run_gcp_eval.sh
# EVAL_LIMIT=10 by default; uses infra/cloudbuild-eval.yaml
```

That Cloud Build job harvests live retrieval from Qdrant, runs **`evals/ragas_eval --harvested --persist`**, and writes to Cloud SQL.

**Vercel (trace links on `/eval`, not required for the list):**

- **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** — e.g. `https://us.cloud.langfuse.com` (must match your Langfuse region; API sets `LANGFUSE_HOST` to US in deploy).
- **`NEXT_PUBLIC_LANGFUSE_PROJECT_ID`** — optional; improves “Open Langfuse trace” when the stored trace id is bare.

Redeploy the Vercel project after changing **`NEXT_PUBLIC_*`**.

### Ongoing

| What changed | What to push | Which trigger fires |
|---|---|---|
| App code (API / Python) | Changes outside `infra/terraform/**` and (usually) `web/**` | `deploy` |
| Web UI only (Vercel) | `web/**` | **Vercel** (not Cloud Build — remove `web-deploy` trigger if stale) |
| Web UI on Cloud Run (optional) | `web/**` | Manual `cloudbuild-web` or opt-in `web-deploy` (`QUERYMESH_ENABLE_CLOUD_RUN_WEB=1` at bootstrap) |
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
