#!/usr/bin/env bash
# bootstrap_gcp.sh — one-time GCP project setup for querymesh.
#
# Run from Cloud Shell (https://shell.cloud.google.com) — ADC pre-configured,
# gcloud + terraform pre-installed. No laptop required.
#
# What this does (idempotent — safe to re-run):
#   1. Pre-flight: secret scan on the repo
#   2. Enable required GCP APIs
#   3. Create GCS bucket for Terraform remote state
#   4. Create Artifact Registry Docker repo
#   5. Create Secret Manager secrets (prompts for values)
#   6. Grant IAM roles to Cloud Build SA and Cloud Run SA
#   7. Create Cloud Build GitHub triggers
#
# After this script:
#   - Push infra/terraform/** changes to main → terraform apply fires automatically
#   - Push any app code change to main → build + migrate + deploy fires automatically
#
# ONE browser step required: GitHub OAuth for Cloud Build.
# The script prints the Cloud Console URL when you reach that step.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — edit if your project/region differ
# ---------------------------------------------------------------------------
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="us-central1"
TF_STATE_BUCKET="${PROJECT_ID}-tf-state"
AR_REPO="querymesh"
CB_GITHUB_REPO=""  # set via prompt below

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BOLD}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
require() { echo -e "${RED}[REQUIRED]${NC} $*"; }
step()    { echo ""; echo -e "${BOLD}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# 0. Validate project
# ---------------------------------------------------------------------------
if [[ -z "$PROJECT_ID" ]]; then
  require "GOOGLE_CLOUD_PROJECT is not set and gcloud has no default project."
  require "Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi
info "Project: ${PROJECT_ID}  Region: ${REGION}"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
CR_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# ---------------------------------------------------------------------------
# 0b. Secret scan — abort on strict failures
# ---------------------------------------------------------------------------
step "Pre-flight: secret scan"
if [[ -f "scripts/check_secrets.sh" ]]; then
  bash scripts/check_secrets.sh || {
    warn "Secret scan reported findings. Review above before continuing."
    read -rp "Continue anyway? (yes/no): " CONT
    [[ "$CONT" == "yes" ]] || { echo "Aborted."; exit 1; }
  }
else
  warn "scripts/check_secrets.sh not found — skipping scan"
fi

# ---------------------------------------------------------------------------
# 1. Enable APIs
# ---------------------------------------------------------------------------
step "Enabling GCP APIs"
APIS=(
  cloudbuild.googleapis.com
  run.googleapis.com
  sqladmin.googleapis.com
  redis.googleapis.com
  secretmanager.googleapis.com
  artifactregistry.googleapis.com
  discoveryengine.googleapis.com
  vpcaccess.googleapis.com
  iam.googleapis.com
)
for api in "${APIS[@]}"; do
  if gcloud services list --project="$PROJECT_ID" --filter="name:$api" --format='value(name)' | grep -q .; then
    ok "$api already enabled"
  else
    info "Enabling $api ..."
    gcloud services enable "$api" --project="$PROJECT_ID"
    ok "$api enabled"
  fi
done

# ---------------------------------------------------------------------------
# 2. GCS bucket for Terraform state
# ---------------------------------------------------------------------------
step "Terraform state bucket"
if gsutil ls -p "$PROJECT_ID" "gs://${TF_STATE_BUCKET}" &>/dev/null; then
  ok "Bucket gs://${TF_STATE_BUCKET} already exists"
else
  info "Creating gs://${TF_STATE_BUCKET} ..."
  gsutil mb -p "$PROJECT_ID" -l "$REGION" -b on "gs://${TF_STATE_BUCKET}"
  gsutil versioning set on "gs://${TF_STATE_BUCKET}"
  ok "Created gs://${TF_STATE_BUCKET} with versioning"
fi

# ---------------------------------------------------------------------------
# 3. Artifact Registry
# ---------------------------------------------------------------------------
step "Artifact Registry"
if gcloud artifacts repositories describe "$AR_REPO" \
     --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  ok "Repository ${AR_REPO} already exists"
else
  info "Creating Artifact Registry repo ${AR_REPO} ..."
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="querymesh API images"
  ok "Created ${AR_REPO}"
fi

# ---------------------------------------------------------------------------
# 4. Secret Manager secrets
# ---------------------------------------------------------------------------
step "Secret Manager secrets"

create_secret() {
  local name="$1"
  local prompt="$2"
  local optional="${3:-false}"

  if gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
    ok "Secret ${name} already exists — skipping (use 'gcloud secrets versions add' to rotate)"
    return
  fi

  if [[ "$optional" == "true" ]]; then
    read -rp "  ${name} (press Enter to skip): " VAL
    [[ -z "$VAL" ]] && { warn "Skipping optional secret ${name}"; return; }
  else
    while true; do
      read -rsp "  ${prompt}: " VAL; echo
      [[ -n "$VAL" ]] && break
      warn "Value required for ${name}"
    done
  fi

  printf '%s' "$VAL" | gcloud secrets create "$name" \
    --project="$PROJECT_ID" \
    --replication-policy=user-managed \
    --locations="$REGION" \
    --data-file=-
  ok "Created secret ${name}"
}

require "You will be prompted for each secret value. Values are sent directly to Secret Manager."
echo ""
create_secret "API_KEY_PEPPER"    "API_KEY_PEPPER (long random string used to HMAC API keys)"
create_secret "DB_PASSWORD"       "DB_PASSWORD (Postgres password for querymesh user)"
create_secret "QDRANT_API_KEY"    "QDRANT_API_KEY (random string; set the same on the Qdrant Cloud Run service)"
create_secret "E2B_API_KEY"       "E2B_API_KEY (from e2b.dev dashboard)"
create_secret "LANGFUSE_PUBLIC_KEY" "LANGFUSE_PUBLIC_KEY" "true"
create_secret "LANGFUSE_SECRET_KEY" "LANGFUSE_SECRET_KEY" "true"
create_secret "PORTAL_JWT_SECRET"   "PORTAL_JWT_SECRET (random string for account portal JWTs)" "true"
# INGEST_SERVICE_KEY: a pre-minted querymesh API key used by Cloud Build to call POST /ingest.
# After first deploy, run: PYTHONPATH=. uv run python scripts/mint_api_key.py
# then store the raw key: echo -n "RAW_KEY" | gcloud secrets create INGEST_SERVICE_KEY --data-file=- --project=$PROJECT_ID
# For now, create a placeholder — update it after first deploy.
create_secret "INGEST_SERVICE_KEY" "INGEST_SERVICE_KEY (querymesh API key for ingest — mint after first deploy, enter placeholder now)" "true"
create_secret "QDRANT_URL"         "QDRANT_URL (Cloud Run Qdrant internal URL — copy from: terraform output qdrant_url)"

# ---------------------------------------------------------------------------
# 5. IAM roles
# ---------------------------------------------------------------------------
step "IAM grants"

grant_role() {
  local member="$1" role="$2"
  if gcloud projects get-iam-policy "$PROJECT_ID" \
       --flatten="bindings[].members" \
       --filter="bindings.role:${role} AND bindings.members:${member}" \
       --format='value(bindings.members)' 2>/dev/null | grep -q .; then
    ok "  ${member} already has ${role}"
  else
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$member" --role="$role" --quiet
    ok "  Granted ${role} → ${member}"
  fi
}

info "Cloud Build SA: ${CB_SA}"
grant_role "serviceAccount:${CB_SA}" "roles/run.admin"
grant_role "serviceAccount:${CB_SA}" "roles/artifactregistry.writer"
grant_role "serviceAccount:${CB_SA}" "roles/iam.serviceAccountUser"
grant_role "serviceAccount:${CB_SA}" "roles/cloudsql.client"
grant_role "serviceAccount:${CB_SA}" "roles/secretmanager.secretAccessor"

info "Cloud Run SA: ${CR_SA}"
grant_role "serviceAccount:${CR_SA}" "roles/secretmanager.secretAccessor"
grant_role "serviceAccount:${CR_SA}" "roles/cloudsql.client"
grant_role "serviceAccount:${CR_SA}" "roles/discoveryengine.viewer"

# Grant Cloud Build SA access to each secret explicitly
for secret in API_KEY_PEPPER DB_PASSWORD QDRANT_API_KEY QDRANT_URL E2B_API_KEY \
              LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY PORTAL_JWT_SECRET INGEST_SERVICE_KEY; do
  if gcloud secrets describe "$secret" --project="$PROJECT_ID" &>/dev/null; then
    gcloud secrets add-iam-policy-binding "$secret" \
      --project="$PROJECT_ID" \
      --member="serviceAccount:${CB_SA}" \
      --role="roles/secretmanager.secretAccessor" \
      --quiet 2>/dev/null || true
  fi
done
ok "Per-secret IAM bindings set for Cloud Build SA"

# ---------------------------------------------------------------------------
# 6. Cloud Build GitHub triggers
# ---------------------------------------------------------------------------
step "Cloud Build GitHub triggers"

echo ""
echo -e "${YELLOW}GitHub connection requires one browser step.${NC}"
echo "Open this URL and connect your GitHub repo to Cloud Build:"
echo ""
echo -e "  ${BOLD}https://console.cloud.google.com/cloud-build/triggers/connect?project=${PROJECT_ID}${NC}"
echo ""
echo "Steps in the UI:"
echo "  1. Select 'GitHub (Cloud Build GitHub App)'"
echo "  2. Authorize and install the Cloud Build GitHub App on your repo"
echo "  3. Select the querymesh repository"
echo "  4. Click 'Connect' then 'Done'"
echo ""
read -rp "Paste your GitHub owner/repo (e.g. myorg/querymesh) once connected: " CB_GITHUB_REPO

if [[ -z "$CB_GITHUB_REPO" ]]; then
  warn "No GitHub repo provided — skipping trigger creation."
  warn "Create triggers manually: https://console.cloud.google.com/cloud-build/triggers"
else
  GH_OWNER="${CB_GITHUB_REPO%%/*}"
  GH_REPO="${CB_GITHUB_REPO##*/}"

  # Trigger: app deploy (push to main, non-terraform files)
  if gcloud builds triggers describe "deploy" \
       --project="$PROJECT_ID" --region="$REGION" &>/dev/null; then
    ok "Trigger 'deploy' already exists"
  else
    gcloud builds triggers create github \
      --project="$PROJECT_ID" \
      --region="$REGION" \
      --name="deploy" \
      --repo-owner="$GH_OWNER" \
      --repo-name="$GH_REPO" \
      --branch-pattern="^main$" \
      --build-config="infra/cloudbuild.yaml" \
      --included-files="**" \
      --ignored-files="infra/terraform/**" \
      --description="Build, migrate, and deploy api service on push to main"
    ok "Created trigger: deploy"
  fi

  # Trigger: terraform apply (push to main, terraform files only)
  if gcloud builds triggers describe "tf-apply" \
       --project="$PROJECT_ID" --region="$REGION" &>/dev/null; then
    ok "Trigger 'tf-apply' already exists"
  else
    gcloud builds triggers create github \
      --project="$PROJECT_ID" \
      --region="$REGION" \
      --name="tf-apply" \
      --repo-owner="$GH_OWNER" \
      --repo-name="$GH_REPO" \
      --branch-pattern="^main$" \
      --build-config="infra/cloudbuild.tf.yaml" \
      --included-files="infra/terraform/**" \
      --description="Run terraform apply when infra/terraform/** changes on main"
    ok "Created trigger: tf-apply"
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}=== Bootstrap complete ===${NC}"
echo ""
echo "Next steps:"
echo "  1. Push the infra/terraform/ directory to main"
echo "     → Cloud Build 'tf-apply' trigger fires → provisions Cloud SQL, Redis, Qdrant, VPC"
echo ""
echo "  2. Push any app code change to main"
echo "     → Cloud Build 'deploy' trigger fires → build + migrate + deploy + ingest"
echo ""
echo "  3. Monitor at:"
echo "     https://console.cloud.google.com/cloud-build/builds?project=${PROJECT_ID}"
echo ""
echo "Terraform state bucket : gs://${TF_STATE_BUCKET}"
echo "Artifact Registry      : ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
