# Production infrastructure (GCP — us-central1)

Provision these three backing services **before** the first `gcloud builds submit`. All three
must be reachable from Cloud Run in `us-central1`.

---

## 1. Postgres — Cloud SQL

**Recommended:** Cloud SQL for PostgreSQL 16, single-zone (or HA for production SLOs).

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
INSTANCE=querymesh-pg

# Create instance (~5 min)
gcloud sql instances create $INSTANCE \
  --database-version=POSTGRES_16 \
  --tier=db-g1-small \
  --region=$REGION \
  --storage-type=SSD \
  --storage-size=10GB \
  --no-backup   # add --backup-start-time=03:00 for production

# Create DB and user
gcloud sql databases create querymesh --instance=$INSTANCE
gcloud sql users create querymesh --instance=$INSTANCE --password=CHANGE_ME
```

Get the connection string for Cloud Run (uses Unix socket via Cloud SQL Auth Proxy):

```text
postgresql+asyncpg://querymesh:CHANGE_ME@/querymesh?host=/cloudsql/PROJECT_ID:us-central1:querymesh-pg
```

Store it in Secret Manager:

```bash
echo -n 'postgresql+asyncpg://querymesh:CHANGE_ME@/querymesh?host=/cloudsql/PROJECT_ID:us-central1:querymesh-pg' \
  | gcloud secrets create DATABASE_URL --data-file=-
```

Grant the Cloud Run service account access to Cloud SQL:

```bash
# Identify your Cloud Run SA (default: PROJECT_NUMBER-compute@developer.gserviceaccount.com)
SA=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')@cloudservices.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" \
  --role=roles/cloudsql.client
```

Add `--add-cloudsql-instances=PROJECT_ID:us-central1:querymesh-pg` to the `gcloud run deploy`
line in [infra/cloudbuild.yaml](../infra/cloudbuild.yaml) via `_EXTRA_DEPLOY_ARGS`.

Run Alembic migrations **before** first deploy:

```bash
# From laptop or Cloud Shell, with DATABASE_URL exported (use TCP while Cloud SQL Auth Proxy runs)
DATABASE_URL=postgresql+asyncpg://querymesh:CHANGE_ME@127.0.0.1:5432/querymesh \
  uv run alembic upgrade head
```

---

## 2. Redis — Cloud Memorystore

**Recommended:** Memorystore for Redis 7, Basic tier (or Standard tier for HA).

```bash
REDIS_INSTANCE=querymesh-redis

gcloud redis instances create $REDIS_INSTANCE \
  --size=1 \
  --region=$REGION \
  --redis-version=redis_7_0 \
  --tier=basic

# Get the host IP
REDIS_HOST=$(gcloud redis instances describe $REDIS_INSTANCE \
  --region=$REGION --format='value(host)')
REDIS_PORT=$(gcloud redis instances describe $REDIS_INSTANCE \
  --region=$REGION --format='value(port)')

echo "Redis: redis://$REDIS_HOST:$REDIS_PORT/0"
```

Store in Secret Manager:

```bash
echo -n "redis://$REDIS_HOST:$REDIS_PORT/0" | gcloud secrets create REDIS_URL --data-file=-
```

**VPC connector required:** Cloud Run must have a [VPC connector](https://cloud.google.com/run/docs/configuring/connecting-vpc)
to reach Memorystore (private IP). Create one if you don't already have one:

```bash
gcloud compute networks vpc-access connectors create querymesh-connector \
  --region=$REGION \
  --subnet=default \
  --subnet-project=$PROJECT_ID \
  --min-instances=2 \
  --max-instances=3

# Add to _EXTRA_DEPLOY_ARGS in cloudbuild.yaml:
# --vpc-connector=querymesh-connector --vpc-egress=private-ranges-only
```

---

## 3. Qdrant — Cloud Run service

Deploy the official Qdrant image as a separate Cloud Run service (spec §12: 2 CPU / 4 Gi, min
instances 1 to keep vectors in memory).

```bash
QDRANT_SERVICE=qdrant

gcloud run deploy $QDRANT_SERVICE \
  --image=qdrant/qdrant:latest \
  --region=$REGION \
  --platform=managed \
  --cpu=2 \
  --memory=4Gi \
  --min-instances=1 \
  --max-instances=3 \
  --port=6333 \
  --no-allow-unauthenticated \
  --set-env-vars=QDRANT__SERVICE__API_KEY=CHANGE_ME

# Get the Qdrant service URL
QDRANT_URL=$(gcloud run services describe $QDRANT_SERVICE \
  --region=$REGION --format='value(status.url)')

echo "Qdrant: $QDRANT_URL"
```

Store in Secret Manager:

```bash
echo -n "$QDRANT_URL" | gcloud secrets create QDRANT_URL --data-file=-
echo -n 'CHANGE_ME' | gcloud secrets create QDRANT_API_KEY --data-file=-
```

**Persistence:** by default, Qdrant on Cloud Run loses vectors on revision restart. For
production, mount a Cloud Filestore NFS volume or use Qdrant Cloud instead of a self-hosted
Cloud Run service. Qdrant Cloud (cloud.qdrant.io) provides a managed cluster with a stable URL
and API key — simpler for production.

---

## 4. Wire everything into `cloudbuild.yaml`

After provisioning, the full deploy command looks like:

```bash
gcloud builds submit --config infra/cloudbuild.yaml \
  --substitutions=_EXTRA_DEPLOY_ARGS="
    --set-secrets=DATABASE_URL=DATABASE_URL:latest,REDIS_URL=REDIS_URL:latest,QDRANT_URL=QDRANT_URL:latest,QDRANT_API_KEY=QDRANT_API_KEY:latest
    --add-cloudsql-instances=PROJECT_ID:us-central1:querymesh-pg
    --vpc-connector=querymesh-connector
    --vpc-egress=private-ranges-only
    --set-env-vars=GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,QDRANT_COLLECTION=gcp_docs
  "
```

Run Alembic **before** this (see §1 above).

---

## 5. Post-deploy checklist

- `GET /health` — verify `postgres`, `redis`, `qdrant` are all `true`
- Trigger corpus ingest: `POST /ingest {"source":"gcp_docs"}` (API must reach Qdrant)
- Enable `RAG_VERTEX_RERANK=true` (Cloud Run env var) after enabling Discovery Engine API
- Set up log-based metrics + alert policies — see [docs/cloud_logging_metrics.md](cloud_logging_metrics.md)
- Set `LANGFUSE_TRACING_ENVIRONMENT=production` and add Langfuse secrets for trace correlation
