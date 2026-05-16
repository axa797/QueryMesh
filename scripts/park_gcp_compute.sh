#!/usr/bin/env bash
# Park billable compute: Cloud Run api+qdrant (scale to 0) + stop Cloud SQL.
# Keeps Redis, VPC connector, secrets, and images. Does not disable Cloud Build triggers.
#
# Usage: bash scripts/park_gcp_compute.sh

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GOOGLE_CLOUD_PROJECT or: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

echo "Project=${PROJECT_ID} Region=${REGION}"
echo "Scaling Cloud Run api and qdrant to min-instances=0 ..."
gcloud run services update api \
  --project="${PROJECT_ID}" --region="${REGION}" --quiet \
  --min-instances=0

gcloud run services update qdrant \
  --project="${PROJECT_ID}" --region="${REGION}" --quiet \
  --min-instances=0

echo "Stopping Cloud SQL querymesh-pg (storage still billed) ..."
gcloud sql instances patch querymesh-pg \
  --project="${PROJECT_ID}" \
  --activation-policy=NEVER \
  --quiet

echo ""
echo "Parked: api, qdrant (scale-to-zero), SQL (stopped). Redis unchanged."
echo "Optional: pause Cloud Build triggers (deploy, tf-apply) to avoid accidental wake on git push."
echo "Wake: bash scripts/wake_gcp_compute.sh"
