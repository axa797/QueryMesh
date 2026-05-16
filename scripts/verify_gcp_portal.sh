#!/usr/bin/env bash
# Read-only checks: Secret Manager + Cloud Run api env for portal / Google OAuth.
# Does not print secret values (except non-secret hosts/URLs for redirect/frontend checks).
# Exit 1 if anything required is missing or production values drift.
#
# Usage (Cloud Shell or machine with gcloud + jq):
#   bash scripts/verify_gcp_portal.sh
#   VERIFY_VALUES=1 bash scripts/verify_gcp_portal.sh   # compare SM values to prod expectations (default: 1)
#   VERIFY_HEALTH=1 bash scripts/verify_gcp_portal.sh   # also GET /health
#   EXPECTED_PORTAL_FRONTEND_BASE_URL=https://query-mesh.vercel.app bash scripts/verify_gcp_portal.sh
#   REGION=us-east1 SERVICE=api bash scripts/verify_gcp_portal.sh

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-api}"
VERIFY_HEALTH="${VERIFY_HEALTH:-0}"
VERIFY_VALUES="${VERIFY_VALUES:-1}"
EXPECTED_PORTAL_FRONTEND_BASE_URL="${EXPECTED_PORTAL_FRONTEND_BASE_URL:-https://query-mesh.vercel.app}"

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

ENV_NAMES=$(echo "$JSON" | jq -r '(.spec.template.spec.containers[0].env // []) | .[] | .name' 2>/dev/null || true)

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
EXPECTED_REDIRECT=""
if [[ -n "${API_URL}" ]]; then
  EXPECTED_REDIRECT="${API_URL}/account/oauth/google/callback"
  echo ""
  echo -e "${BOLD}Public URL:${NC} ${API_URL}"
  echo -e "${YELLOW}Google OAuth redirect URI (must match exactly in Google Console):${NC}"
  echo "  ${EXPECTED_REDIRECT}"
fi

# --- Production value checks (Secret Manager) ---
if [[ "${VERIFY_VALUES}" == "1" ]] && [[ "${FAIL}" -eq 0 ]]; then
  echo ""
  echo -e "${BOLD}=== Secret value checks (prod) ===${NC}"
  EXPECTED_FRONT="${EXPECTED_PORTAL_FRONTEND_BASE_URL%/}"

  read_secret() {
    gcloud secrets versions access latest --project="${PROJECT_ID}" --secret="$1" 2>/dev/null || echo ""
  }

  redir=$(read_secret GOOGLE_OAUTH_REDIRECT_URI)
  front=$(read_secret PORTAL_FRONTEND_BASE_URL)
  cid=$(read_secret GOOGLE_OAUTH_CLIENT_ID)
  jwt=$(read_secret PORTAL_JWT_SECRET)

  if [[ -n "${EXPECTED_REDIRECT}" ]]; then
    if [[ "${redir}" == "${EXPECTED_REDIRECT}" ]]; then
      echo -e "${GREEN}[ok value]${NC} GOOGLE_OAUTH_REDIRECT_URI matches Cloud Run status.url"
    else
      echo -e "${RED}[bad value]${NC} GOOGLE_OAUTH_REDIRECT_URI does not match ${EXPECTED_REDIRECT}"
      echo -e "  Run: bash scripts/sync_gcp_portal_secrets.sh"
      FAIL=1
    fi
  fi

  if [[ "${front}" == "${EXPECTED_FRONT}" ]]; then
    echo -e "${GREEN}[ok value]${NC} PORTAL_FRONTEND_BASE_URL = ${EXPECTED_FRONT}"
  else
    echo -e "${RED}[bad value]${NC} PORTAL_FRONTEND_BASE_URL expected ${EXPECTED_FRONT}"
    echo -e "  Run: bash scripts/sync_gcp_portal_secrets.sh"
    FAIL=1
  fi

  case "${front}" in
    *localhost*|*127.0.0.1*|http://*)
      echo -e "${RED}[bad value]${NC} PORTAL_FRONTEND_BASE_URL must not be localhost or http in production"
      FAIL=1
      ;;
  esac

  if [[ -z "${cid}" ]]; then
    echo -e "${RED}[empty]${NC} GOOGLE_OAUTH_CLIENT_ID"
    FAIL=1
  fi
  if [[ -z "${jwt}" ]]; then
    echo -e "${RED}[empty]${NC} PORTAL_JWT_SECRET"
    FAIL=1
  fi

  # CORS literals on Cloud Run (not secrets)
  CORS_ORIGINS=$(echo "$JSON" | jq -r '
    (.spec.template.spec.containers[0].env // [])
    | map(select(.name == "CORS_ALLOW_ORIGINS")) | .[0].value // empty')
  if [[ -n "${CORS_ORIGINS}" ]] && [[ "${CORS_ORIGINS}" != "*" ]]; then
    cors_ok=0
    if [[ "${CORS_ORIGINS}" == "${EXPECTED_FRONT}" ]]; then
      cors_ok=1
    elif echo "${CORS_ORIGINS}" | tr ',' '\n' | grep -qx "${EXPECTED_FRONT}"; then
      cors_ok=1
    fi
    if [[ "${cors_ok}" -eq 1 ]]; then
      echo -e "${GREEN}[ok cors]${NC} CORS_ALLOW_ORIGINS includes ${EXPECTED_FRONT}"
    else
      echo -e "${YELLOW}[warn cors]${NC} CORS_ALLOW_ORIGINS may not include ${EXPECTED_FRONT} (got: ${CORS_ORIGINS})"
      echo -e "  Preview *.vercel.app may still work via CORS_ALLOW_ORIGIN_REGEX; run tf-apply if prod origin is missing."
    fi
  fi
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
    oauth_ok=$(echo "$BODY" | jq -r '.capabilities.oauth_env_configured // false')
    if [[ "${oauth_ok}" == "true" ]]; then
      echo -e "${GREEN}[ok] oauth_env_configured${NC}"
    else
      echo -e "${RED}[fail] capabilities.oauth_env_configured is not true${NC}"
      FAIL=1
    fi
    front_host=$(echo "$BODY" | jq -r '.capabilities.portal_frontend_origin // empty')
    if [[ -n "${front_host}" ]] && [[ "${VERIFY_VALUES}" == "1" ]]; then
      expected_host=$(python3 -c "from urllib.parse import urlparse; print(urlparse('${EXPECTED_PORTAL_FRONTEND_BASE_URL}').netloc)")
      if [[ "${front_host}" == "${expected_host}" ]]; then
        echo -e "${GREEN}[ok] portal_frontend_origin=${front_host}${NC}"
      else
        echo -e "${RED}[fail] portal_frontend_origin=${front_host} expected ${expected_host}${NC}"
        FAIL=1
      fi
    fi
    echo -e "${GREEN}[ok] HTTP /health${NC}"
  fi
fi

echo ""
if [[ "${FAIL}" -ne 0 ]]; then
  echo -e "${RED}Verification FAILED.${NC}"
  echo "Fix: bash scripts/sync_gcp_portal_secrets.sh, tf-apply (reconcile-deploy), redeploy api."
  echo "See infra/README.md (OAuth go-live)."
  exit 1
fi

echo -e "${GREEN}Verification passed.${NC}"
exit 0
