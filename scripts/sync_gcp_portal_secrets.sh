#!/usr/bin/env bash
# sync_gcp_portal_secrets.sh — idempotent production sync for portal OAuth env secrets.
#
# Derives GOOGLE_OAUTH_REDIRECT_URI from the live Cloud Run api status.url.
# Sets PORTAL_FRONTEND_BASE_URL from EXPECTED_PORTAL_FRONTEND_BASE_URL (never sources .env).
#
# Does NOT create or rotate GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET /
# PORTAL_JWT_SECRET — use scripts/bootstrap_gcp.sh for first-time setup.
#
# Usage:
#   bash scripts/sync_gcp_portal_secrets.sh
#   EXPECTED_PORTAL_FRONTEND_BASE_URL=https://query-mesh.vercel.app bash scripts/sync_gcp_portal_secrets.sh
#   ROLL_API=0 bash scripts/sync_gcp_portal_secrets.sh   # skip Cloud Run revision roll

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-api}"
EXPECTED_PORTAL_FRONTEND_BASE_URL="${EXPECTED_PORTAL_FRONTEND_BASE_URL:-https://query-mesh.vercel.app}"
ROLL_API="${ROLL_API:-1}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info() { echo -e "${BOLD}[INFO]${NC} $*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()  { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

if [[ -z "${PROJECT_ID}" ]]; then
  die "Set GOOGLE_CLOUD_PROJECT or: gcloud config set project YOUR_PROJECT_ID"
fi

if [[ -f .env ]] && [[ "${ALLOW_DOTENV:-}" != "1" ]]; then
  warn "This script does not source .env. Set EXPECTED_PORTAL_FRONTEND_BASE_URL explicitly if needed."
fi

FRONT="${EXPECTED_PORTAL_FRONTEND_BASE_URL%/}"
case "${FRONT}" in
  *localhost*|*127.0.0.1*)
    die "Refusing to sync localhost frontend URL: ${FRONT}"
    ;;
esac

API_URL=$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')
[[ -n "${API_URL}" ]] || die "Cloud Run service ${SERVICE} has no status.url"
REDIRECT_URI="${API_URL}/account/oauth/google/callback"

info "Project: ${PROJECT_ID}  Region: ${REGION}  Service: ${SERVICE}"
info "API URL: ${API_URL}"
info "GOOGLE_OAUTH_REDIRECT_URI → ${REDIRECT_URI}"
info "PORTAL_FRONTEND_BASE_URL → ${FRONT}"

PN=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
CR_SA="${PN}-compute@developer.gserviceaccount.com"

grant_accessor() {
  local name="$1"
  gcloud secrets add-iam-policy-binding "${name}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${CR_SA}" --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null 2>&1 || true
}

# Returns 0 if a new version was written, 1 if unchanged.
upsert_secret() {
  local name="$1" value="$2"
  local current=""
  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    current=$(gcloud secrets versions access latest --project="${PROJECT_ID}" --secret="${name}" 2>/dev/null || echo "")
  else
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --project="${PROJECT_ID}" \
      --replication-policy=user-managed \
      --locations="${REGION}" \
      --data-file=- >/dev/null
    ok "Created secret ${name}"
    grant_accessor "${name}"
    return 0
  fi
  if [[ "${current}" == "${value}" ]]; then
    ok "Secret ${name} unchanged"
    return 1
  fi
  printf '%s' "${value}" | gcloud secrets versions add "${name}" \
    --project="${PROJECT_ID}" --data-file=- >/dev/null
  ok "Updated secret ${name} (new version)"
  grant_accessor "${name}"
  return 0
}

CHANGED=0
if upsert_secret GOOGLE_OAUTH_REDIRECT_URI "${REDIRECT_URI}"; then
  CHANGED=1
fi
if upsert_secret PORTAL_FRONTEND_BASE_URL "${FRONT}"; then
  CHANGED=1
fi

if [[ "${ROLL_API}" == "1" ]] && [[ "${CHANGED}" -eq 1 ]]; then
  info "Rolling Cloud Run ${SERVICE} to pick up :latest secret versions..."
  gcloud run services update "${SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --quiet \
    --update-secrets="GOOGLE_OAUTH_REDIRECT_URI=GOOGLE_OAUTH_REDIRECT_URI:latest,PORTAL_FRONTEND_BASE_URL=PORTAL_FRONTEND_BASE_URL:latest"
  ok "Cloud Run revision updated"
elif [[ "${CHANGED}" -eq 0 ]]; then
  ok "No secret changes; Cloud Run roll skipped"
fi

echo ""
warn "Manual checklist (not automated):"
echo "  1. Google Console → OAuth Web client → Authorized redirect URIs:"
echo "       ${REDIRECT_URI}"
echo "  2. Google Console → Authorized JavaScript origins:"
echo "       ${FRONT}"
echo "  3. Vercel → NEXT_PUBLIC_QUERYMESH_URL = ${API_URL} (redeploy frontend after change)"
echo ""
echo "Verify: VERIFY_VALUES=1 bash scripts/verify_gcp_portal.sh"
