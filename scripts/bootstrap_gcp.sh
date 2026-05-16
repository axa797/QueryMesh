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
#
# Optional Cloud Build trigger "web-deploy" (Next.js → Cloud Run service "web"):
#   Skipped by default — use Vercel for the frontend instead.
#   To create that trigger on bootstrap: QUERYMESH_ENABLE_CLOUD_RUN_WEB=1 bash scripts/bootstrap_gcp.sh
#   To remove an existing trigger: gcloud builds triggers delete web-deploy --region=us-central1 --project=PROJECT_ID

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
  # Required by terraform's data "google_project" lookup at plan time —
  # MUST be enabled here, not in apis.tf (apis.tf can't help with a chicken-and-egg
  # where plan needs the API to even compute the plan).
  cloudresourcemanager.googleapis.com
  cloudbuild.googleapis.com
  run.googleapis.com
  sqladmin.googleapis.com
  redis.googleapis.com
  secretmanager.googleapis.com
  artifactregistry.googleapis.com
  discoveryengine.googleapis.com
  vpcaccess.googleapis.com
  iam.googleapis.com
  # Compute API is required for VPC Serverless Access connector (network.tf).
  compute.googleapis.com
  # Used downstream by ingestion + evals.
  aiplatform.googleapis.com
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

# Set cleanup policy: keep the 5 most recent tagged versions; delete untagged after 1 day.
# This prevents old :BUILD_ID images from accumulating indefinitely in Artifact Registry.
info "Setting Artifact Registry cleanup policy ..."
cat > /tmp/ar-cleanup-policy.json << 'EOF'
[
  {
    "name": "keep-5-most-recent",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": 5}
  },
  {
    "name": "delete-untagged",
    "action": {"type": "Delete"},
    "condition": {"tagState": "untagged", "olderThan": "86400s"}
  }
]
EOF
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --policy=/tmp/ar-cleanup-policy.json \
  --no-dry-run 2>/dev/null || warn "Cleanup policy requires Artifact Registry API v1beta2 — set manually if needed"
ok "Cleanup policy set (keep 5 tagged versions, delete untagged after 1 day)"

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
# User-supplied secrets (values you know at bootstrap time).
create_secret "API_KEY_PEPPER"      "API_KEY_PEPPER (long random string used to HMAC API keys)"
create_secret "DB_PASSWORD"         "DB_PASSWORD (Postgres password for querymesh user)"
create_secret "QDRANT_API_KEY"      "QDRANT_API_KEY (random string; set the same on the Qdrant Cloud Run service)"
create_secret "E2B_API_KEY"         "E2B_API_KEY (from e2b.dev dashboard)"
create_secret "LANGFUSE_PUBLIC_KEY" "LANGFUSE_PUBLIC_KEY" "true"
create_secret "LANGFUSE_SECRET_KEY" "LANGFUSE_SECRET_KEY" "true"
create_secret "PORTAL_JWT_SECRET"   "PORTAL_JWT_SECRET (random string for account portal JWTs)" "true"
# Optional Google OAuth — all four must exist in Secret Manager + IAM below for Cloud Run to bind them.
# Redirect URI must match an authorized URI in Google Cloud Console (API callback path).
create_secret "GOOGLE_OAUTH_CLIENT_ID"     "GOOGLE_OAUTH_CLIENT_ID (OAuth Web client ID; Enter to skip)" "true"
create_secret "GOOGLE_OAUTH_CLIENT_SECRET" "GOOGLE_OAUTH_CLIENT_SECRET (OAuth client secret; Enter to skip)" "true"
create_secret "GOOGLE_OAUTH_REDIRECT_URI"  "GOOGLE_OAUTH_REDIRECT_URI (e.g. https://YOUR-API/account/oauth/google/callback; Enter to skip)" "true"
create_secret "PORTAL_FRONTEND_BASE_URL"   "PORTAL_FRONTEND_BASE_URL (Next origin, e.g. https://your-web — no trailing slash; Enter to skip)" "true"
# INGEST_TOKEN: a random shared secret used by Cloud Build to call POST /ingest.
# Generate with: openssl rand -hex 32
# No user account needed — this bypasses normal API key auth for service-to-service calls only.
create_secret "INGEST_TOKEN"        "INGEST_TOKEN (random string — generate: openssl rand -hex 32)"

# Derived secrets (DATABASE_URL, REDIS_URL, QDRANT_URL) are NOT created here.
# They are created by terraform (infra/terraform/secrets.tf) with values written
# by the `reconcile-deploy` step in infra/cloudbuild.tf.yaml on every tf-apply.

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

# BUILD_SA: the service account that Cloud Build triggers run as.
# Cloud Build no longer accepts the legacy *@cloudbuild.gserviceaccount.com SA
# at trigger run time — it requires a "user-managed" SA. We reuse the Compute
# Engine default SA, which is also the Cloud Run runtime SA. This keeps the
# permission model simple (one SA, one set of grants) and avoids creating an
# extra dedicated SA for a one-person setup.
BUILD_SA="${CR_SA}"

info "Build / Run SA: ${BUILD_SA}"
grant_role "serviceAccount:${BUILD_SA}" "roles/run.admin"
grant_role "serviceAccount:${BUILD_SA}" "roles/artifactregistry.writer"
grant_role "serviceAccount:${BUILD_SA}" "roles/iam.serviceAccountUser"
grant_role "serviceAccount:${BUILD_SA}" "roles/cloudsql.client"
grant_role "serviceAccount:${BUILD_SA}" "roles/secretmanager.secretAccessor"
grant_role "serviceAccount:${BUILD_SA}" "roles/discoveryengine.viewer"
# Required when build YAML sets options.logging=CLOUD_LOGGING_ONLY.
grant_role "serviceAccount:${BUILD_SA}" "roles/logging.logWriter"
# tf-apply's reconcile step calls `gcloud builds triggers update` to keep the
# deploy trigger's _EXTRA_DEPLOY_ARGS substitution in sync with terraform
# outputs. Requires cloudbuild.builds.editor.
grant_role "serviceAccount:${BUILD_SA}" "roles/cloudbuild.builds.editor"
# tf-apply's reconcile step writes new versions of DATABASE_URL / REDIS_URL /
# QDRANT_URL (secret schemas are created by terraform; version writes happen
# inside the build). Per-secret IAM bindings for these are granted by
# terraform (infra/terraform/secrets.tf), but we also grant project-wide
# secretVersionAdder so the very first run — before terraform has created the
# secrets or the per-secret bindings — can create versions if needed.
grant_role "serviceAccount:${BUILD_SA}" "roles/secretmanager.secretVersionAdder"
# tf-apply runs Terraform as this same SA (regional triggers require a user-managed
# service account; we use the Compute default SA). Terraform needs:
#   - project IAM updates (iam.tf google_project_iam_member)
#   - VPC peering for Cloud SQL private IP (private_services.tf)
#   - per-secret IAM on derived secrets (secrets.tf)
grant_role "serviceAccount:${BUILD_SA}" "roles/resourcemanager.projectIamAdmin"
grant_role "serviceAccount:${BUILD_SA}" "roles/compute.networkAdmin"
grant_role "serviceAccount:${BUILD_SA}" "roles/secretmanager.admin"

# Per-secret accessor bindings for the static, user-supplied secrets
# (DATABASE_URL / REDIS_URL / QDRANT_URL are managed by terraform).
for secret in API_KEY_PEPPER DB_PASSWORD QDRANT_API_KEY E2B_API_KEY \
              LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY PORTAL_JWT_SECRET INGEST_TOKEN \
              GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_REDIRECT_URI \
              PORTAL_FRONTEND_BASE_URL; do
  if gcloud secrets describe "$secret" --project="$PROJECT_ID" &>/dev/null; then
    gcloud secrets add-iam-policy-binding "$secret" \
      --project="$PROJECT_ID" \
      --member="serviceAccount:${BUILD_SA}" \
      --role="roles/secretmanager.secretAccessor" \
      --quiet 2>/dev/null || true
  fi
done
ok "Per-secret IAM bindings set for ${BUILD_SA}"

# ---------------------------------------------------------------------------
# 6. Cloud Build GitHub triggers
# ---------------------------------------------------------------------------
step "Cloud Build GitHub triggers"

echo ""
echo -e "${YELLOW}GitHub connection requires one browser step.${NC}"
echo "Open this URL and install the Cloud Build GitHub App on your repo:"
echo ""
echo -e "  ${BOLD}https://console.cloud.google.com/cloud-build/triggers/connect?project=${PROJECT_ID}${NC}"
echo ""
echo "Steps in the UI:"
echo "  1. Select 'GitHub (Cloud Build GitHub App)'"
echo "  2. Authenticate to GitHub and install the Cloud Build GitHub App on the repo"
echo "  3. (You may stop after install — this script will create the project-side record"
echo "      via the trigger create call below. The wizard's 'Select repository' step is"
echo "      not required and may show 'already connected' even on a fresh project.)"
echo ""
read -rp "Paste your GitHub owner/repo (e.g. myorg/querymesh) once the App is installed: " CB_GITHUB_REPO

# --service-account is mandatory for regional triggers as of Oct 2024.
# Must be in the format projects/PROJECT_ID/serviceAccounts/EMAIL — without it, the
# create API rejects with the unhelpful "Request contains an invalid argument."
# It must also be a user-managed SA — the legacy ${CB_SA} is rejected at trigger
# run time with "provide a user-managed service account". We use ${BUILD_SA}
# (Compute Engine default SA), which is granted the build-time roles above.
TRIGGER_SA="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}"

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
      --ignored-files="infra/terraform/**,web/**" \
      --service-account="$TRIGGER_SA" \
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
      --service-account="$TRIGGER_SA" \
      --description="Run terraform apply when infra/terraform/** changes on main"
    ok "Created trigger: tf-apply"
  fi

  # Optional: Next.js on Cloud Run — most teams use Vercel; leave this off unless needed.
  if [[ "${QUERYMESH_ENABLE_CLOUD_RUN_WEB:-}" == "1" ]]; then
    if gcloud builds triggers describe "web-deploy" \
         --project="$PROJECT_ID" --region="$REGION" &>/dev/null; then
      ok "Trigger 'web-deploy' already exists"
    else
      gcloud builds triggers create github \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --name="web-deploy" \
        --repo-owner="$GH_OWNER" \
        --repo-name="$GH_REPO" \
        --branch-pattern="^main$" \
        --build-config="infra/cloudbuild-web.yaml" \
        --included-files="web/**" \
        --included-files="infra/cloudbuild-web.yaml" \
        --service-account="$TRIGGER_SA" \
        --description="Build and deploy Next.js portal to Cloud Run when web/** changes"
      ok "Created trigger: web-deploy"
    fi
  else
    info "Skipping 'web-deploy' trigger (frontend on Vercel by default). Set QUERYMESH_ENABLE_CLOUD_RUN_WEB=1 to create it."
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
echo "  2b. (Optional) Cloud Run UI: set QUERYMESH_ENABLE_CLOUD_RUN_WEB=1 and re-run bootstrap,"
echo "      or run: gcloud builds submit --config infra/cloudbuild-web.yaml"
echo "      Skip if you use Vercel — delete stale trigger: gcloud builds triggers delete web-deploy --region=${REGION} --project=${PROJECT_ID}"
echo ""
echo "  3. Monitor at:"
echo "     https://console.cloud.google.com/cloud-build/builds?project=${PROJECT_ID}"
echo ""
echo "Terraform state bucket : gs://${TF_STATE_BUCKET}"
echo "Artifact Registry      : ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
