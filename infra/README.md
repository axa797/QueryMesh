# Infrastructure (local + GCP)

- **Local:** [docker-compose.yml](docker-compose.yml) — Postgres, Redis, Qdrant.
- **Container image (API):** [Dockerfile](Dockerfile) — production install via `uv`; listens on `$PORT` (8080 default).

## Cloud Run API (us-central1)

### One-time setup

1. **Artifact Registry** (Docker):

   ```bash
   gcloud artifacts repositories create querymesh \
     --repository-format=docker --location=us-central1 --description=querymesh
   ```

2. **Secret Manager** — create secrets (names must match [cloudbuild.yaml](cloudbuild.yaml) `set-secrets` and any extras you add):

   ```bash
   # HMAC pepper for API keys (required)
   echo -n 'your-pepper' | gcloud secrets create API_KEY_PEPPER --data-file=-

   # E2B (required for code agent in prod)
   echo -n 'e2b_...' | gcloud secrets create E2B_API_KEY --data-file=-

   # Typical: connection strings (use async URL shape the app expects)
   echo -n 'postgresql+asyncpg://...' | gcloud secrets create DATABASE_URL --data-file=-
   echo -n 'redis://...' | gcloud secrets create REDIS_URL --data-file=-

   # Optional: Qdrant + Langfuse
   echo -n 'https://...' | gcloud secrets create QDRANT_URL --data-file=-
   echo -n '...' | gcloud secrets create QDRANT_API_KEY --data-file=-  # if cluster needs it
   echo -n 'pk-...' | gcloud secrets create LANGFUSE_PUBLIC_KEY --data-file=-
   echo -n 'sk-...' | gcloud secrets create LANGFUSE_SECRET_KEY --data-file=-
   ```

3. **Runtime service account** (default Cloud Run SA or a custom SA) needs **`roles/secretmanager.secretAccessor`** on each secret.

4. **Cloud Build SA** (`PROJECT_NUMBER@cloudbuild.gserviceaccount.com`) needs at least:

   - `roles/artifactregistry.writer`
   - `roles/run.admin`
   - `roles/iam.serviceAccountUser` (to deploy Cloud Run)

### Deploy pipeline

Manual submit builds the image, pushes to `us-central1-docker.pkg.dev/PROJECT_ID/querymesh/api:BUILD_ID`, and deploys service **`api`**:

```bash
gcloud builds submit --config infra/cloudbuild.yaml
```

Add DB/Redis (and anything else) via substitution so `gcloud run deploy` receives extra flags:

```bash
gcloud builds submit --config infra/cloudbuild.yaml \
  --substitutions=_EXTRA_DEPLOY_ARGS="--set-secrets=DATABASE_URL=DATABASE_URL:latest,REDIS_URL=REDIS_URL:latest,QDRANT_URL=QDRANT_URL:latest"
```

Run **Alembic** before or after first deploy (Cloud SQL / Postgres reachable from Cloud Run):

```bash
# From your laptop or a Cloud Shell job, with DATABASE_URL pointing at the same DB:
uv run alembic upgrade head
```

### Qdrant on Cloud Run (optional)

Spec §12 targets a dedicated Qdrant service (e.g. **2 CPU / 4Gi**, **min instances 1**). Deploy the official image in the same region and point **`QDRANT_URL`** (and API key if enabled) at it; keep the API’s **`QDRANT_COLLECTION`** aligned with ingestion.

### PR tests

[cloudbuild.pr.yaml](cloudbuild.pr.yaml) runs `uv sync` + fast `pytest` (skips `integration` and `eval`).

## Local image smoke test

```bash
docker build -f infra/Dockerfile -t querymesh:local .
# Requires .env-style variables passed in; see .env.example
docker run --rm -p 8080:8080 -e PORT=8080 ... querymesh:local
```
