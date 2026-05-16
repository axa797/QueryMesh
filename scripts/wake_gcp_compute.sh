#!/usr/bin/env bash
# Wake parked compute: start Cloud SQL, then scale Cloud Run api+qdrant back up.
#
# Order matters for a working app:
#   1. Cloud SQL (API migrations and /health need Postgres)
#   2. qdrant + api (can run together; api deploy uses min-instances=1)
#   3. Optional: corpus ingest if Qdrant was empty (deploy pipeline or POST /ingest)
#
# Redis is left running — no wake step.
#
# Usage:
#   bash scripts/wake_gcp_compute.sh
#   API_MIN_INSTANCES=1 QDRANT_MIN_INSTANCES=1 bash scripts/wake_gcp_compute.sh

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
API_MIN="${API_MIN_INSTANCES:-1}"
QDRANT_MIN="${QDRANT_MIN_INSTANCES:-1}"
SQL_INSTANCE="${SQL_INSTANCE:-querymesh-pg}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GOOGLE_CLOUD_PROJECT or: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

echo "Project=${PROJECT_ID} Region=${REGION}"
echo "Step 1/2: Starting Cloud SQL ${SQL_INSTANCE} ..."
gcloud sql instances patch "${SQL_INSTANCE}" \
  --project="${PROJECT_ID}" \
  --activation-policy=ALWAYS \
  --quiet

echo "Waiting for SQL instance to be RUNNABLE (up to ~5 min) ..."
for _ in $(seq 1 30); do
  state=$(gcloud sql instances describe "${SQL_INSTANCE}" \
    --project="${PROJECT_ID}" --format='value(state)' 2>/dev/null || echo "")
  if [[ "${state}" == "RUNNABLE" ]]; then
    echo "  SQL is RUNNABLE."
    break
  fi
  echo "  state=${state:-unknown}, waiting 10s ..."
  sleep 10
done

echo "Step 2/2: Scaling Cloud Run (qdrant then api) ..."
gcloud run services update qdrant \
  --project="${PROJECT_ID}" --region="${REGION}" --quiet \
  --min-instances="${QDRANT_MIN}"

gcloud run services update api \
  --project="${PROJECT_ID}" --region="${REGION}" --quiet \
  --min-instances="${API_MIN}"

API_URL=$(gcloud run services describe api \
  --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)' 2>/dev/null || echo "")

echo ""
echo "Wake complete."
[[ -n "${API_URL}" ]] && echo "  API URL: ${API_URL}"
echo "  Redis: unchanged (already running)."
echo ""
echo "If chat/RAG returns no hits after long park, re-ingest:"
echo "  push to main (deploy trigger) or POST ${API_URL:-<api>}/ingest with INGEST_TOKEN"
echo "Verify OAuth: bash scripts/verify_gcp_portal.sh"
