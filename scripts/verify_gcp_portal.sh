#!/usr/bin/env bash
# Read-only checks: Secret Manager + Cloud Run api env for portal / Google OAuth.
# Does not print secret values. Exit 1 if anything required is missing.
#
# Usage (Cloud Shell or machine with gcloud + jq):
#   bash scripts/verify_gcp_portal.sh
#   REGION=us-east1 SERVICE=api bash scripts/verify_gcp_portal.sh
#   VERIFY_HEALTH=1 bash scripts/verify_gcp_portal.sh   # GET /health on public URL

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-api}"
VERIFY_HEALTH="${VERIFY_HEALTH:-0}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

if [[ -z "${PROJECT_ID}" ]]; then
  echo -e "${RED}Set GOOGLE_CLOUD_PROJECT or run: gcloud config set project YOUR_PROJECT_ID${NC}" >&2
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo -e "${RED}jq is required (install or use Cloud Shell).${NC}" >&2
  exit 1
fi

FAIL=0

echo -e "${BOLD}Project:${NC} ${PROJECT_ID}  ${BOLD}Region:${NC} ${REGION}  ${BOLD}Service:${NC} ${SERVICE}"
echo ""

# --- Secret Manager: schemas exist (and have at least one version) ---
SECRETS=(
  PORTAL_JWT_SECRET
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REDIRECT_URI
  PORTAL_FRONTEND_BASE_URL
)

for name in "${SECRETS[@]}"; do
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    echo -e "${RED}[missing secret]${NC} ${name}"
    FAIL=1
    continue
  fi
  if ! gcloud secrets versions list "${name}" --project="${PROJECT_ID}" --limit=1 --format='value(name)' 2>/dev/null | grep -q .; then
    echo -e "${RED}[no versions]${NC} ${name}"
    FAIL=1
  else
    echo -e "${GREEN}[ok secret]${NC} ${name}"
  fi
done

echo ""

# --- Cloud Run: expected env vars mounted (names only; values not shown) ---
if ! gcloud run services describe "${SERVICE}" \
      --project="${PROJECT_ID}" --region="${REGION}" &>/dev/null; then
  echo -e "${RED}Cloud Run service '${SERVICE}' not found in ${REGION}.${NC}"
  exit 1
fi

JSON=$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" --format=json)

# Cloud Run (managed) Service JSON: spec.template.spec.containers[0].env
ENV_NAMES=$(echo "$JSON" | jq -r '(.spec.template.spec.containers[0].env // []) | .[] | .name' 2>/dev/null || true)

# Names the API expects for OAuth + portal (see api/settings.py, api/routes/account.py)
REQUIRED=(
  PORTAL_JWT_SECRET
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REDIRECT_URI
  PORTAL_FRONTEND_BASE_URL
)

for name in "${REQUIRED[@]}"; do
  if echo "$ENV_NAMES" | grep -qx "${name}"; then
    echo -e "${GREEN}[ok env]${NC} ${name}"
  else
    echo -e "${RED}[missing env on Cloud Run]${NC} ${name}"
    FAIL=1
  fi
done

API_URL=$(echo "$JSON" | jq -r '.status.url // empty')
if [[ -n "${API_URL}" ]]; then
  echo ""
  echo -e "${BOLD}Public URL:${NC} ${API_URL}"
  echo -e "${YELLOW}Google OAuth redirect URI (must match exactly in Google Console):${NC}"
  echo "  ${API_URL}/account/oauth/google/callback"
fi

# --- Optional: GET /health (no secrets) ---
if [[ "${VERIFY_HEALTH}" == "1" ]] && [[ -n "${API_URL}" ]]; then
  echo ""
  echo -e "${BOLD}GET ${API_URL}/health${NC}"
  if ! BODY=$(curl -sS -f --max-time 15 "${API_URL}/health" 2>/dev/null); then
    echo -e "${RED}[fail] curl /health${NC}"
    FAIL=1
  else
    echo "$BODY" | jq -e . &>/dev/null && echo "$BODY" | jq . || echo "$BODY"
    echo -e "${GREEN}[ok] HTTP /health${NC}"
  fi
fi

echo ""
if [[ "${FAIL}" -ne 0 ]]; then
  echo -e "${RED}Verification FAILED.${NC}"
  echo "Fix: create missing secrets, run tf-apply (reconcile-deploy), redeploy api."
  echo "See infra/README.md (OAuth go-live)."
  exit 1
fi

echo -e "${GREEN}Verification passed.${NC}"
exit 0
