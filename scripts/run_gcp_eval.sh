#!/usr/bin/env bash
# Submit infra/cloudbuild-eval.yaml to harvest + run RAGAS and persist eval_reports in prod.
#
# Usage:
#   bash scripts/run_gcp_eval.sh
#   EVAL_LIMIT=5 bash scripts/run_gcp_eval.sh

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
EVAL_LIMIT="${EVAL_LIMIT:-10}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GOOGLE_CLOUD_PROJECT or: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

echo "Submitting eval build (limit=${EVAL_LIMIT}) to project ${PROJECT_ID} ..."
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --config infra/cloudbuild-eval.yaml \
  --substitutions="_EVAL_LIMIT=${EVAL_LIMIT}"
