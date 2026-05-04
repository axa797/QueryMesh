#!/usr/bin/env bash
# check_secrets.sh — scan the git repo for committed secrets before deploying.
#
# Usage:
#   bash scripts/check_secrets.sh          # warn only
#   bash scripts/check_secrets.sh --strict  # exit 1 on any finding
#
# Called automatically by scripts/bootstrap_gcp.sh before touching GCP.
# Safe to run from Cloud Shell or a local terminal.

set -euo pipefail

STRICT=false
[[ "${1:-}" == "--strict" ]] && STRICT=true

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

FINDINGS=0

warn() { echo -e "${YELLOW}[WARN]${NC} $*"; ((FINDINGS++)) || true; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; ((FINDINGS++)) || true; }
ok()   { echo -e "${GREEN}[ OK ]${NC} $*"; }

echo "=== querymesh secret scan ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Tracked sensitive files
# ---------------------------------------------------------------------------
echo "-- Checking tracked sensitive files --"

TRACKED_SENSITIVE=(
  ".env"
  ".env.local"
  ".env.production"
  ".env.staging"
  "terraform.tfvars"
  "application_default_credentials.json"
)

TRACKED=$(git ls-files 2>/dev/null || true)

for f in "${TRACKED_SENSITIVE[@]}"; do
  # Match the exact filename or path ending in the filename (avoids .env matching .env.example)
  if echo "$TRACKED" | grep -qE "(^|/)${f//./\\.}$"; then
    fail "Tracked sensitive file: $f"
  fi
done

# Check for actual credential file extensions (not filenames that happen to contain "key")
CRED_HITS=$(echo "$TRACKED" | grep -E '\.(pem|p12|key|pfx)$|^service_account.*\.json$' || true)
if [[ -n "$CRED_HITS" ]]; then
  while IFS= read -r hit; do fail "Tracked credential file: $hit"; done <<< "$CRED_HITS"
fi

[[ $FINDINGS -eq 0 ]] && ok "No sensitive files tracked"

# ---------------------------------------------------------------------------
# 2. Secret patterns in git history
# ---------------------------------------------------------------------------
echo ""
echo "-- Scanning git history for secret patterns --"

PATTERNS=(
  'AKIA[0-9A-Z]{16}'                        # AWS access key
  'sk-[A-Za-z0-9]{32,}'                     # OpenAI / generic sk- key (32+ chars = real key)
  'ghp_[A-Za-z0-9]{36}'                     # GitHub personal token
  'pk-lf-[A-Za-z0-9-]{20,}'                 # Langfuse public key
  'sk-lf-[A-Za-z0-9-]{20,}'                 # Langfuse secret key
  'e2b_[A-Za-z0-9]{28,}'                    # E2B API key (28+ alphanum chars, no underscores)
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
  'API_KEY_PEPPER=[A-Za-z0-9!@#%^&*()_+=-]{12,}'  # Pepper with real-looking value (skip placeholders)
  'password=[A-Za-z0-9!@#$%^&*()_+=-]{10,}'        # Real password (10+ chars, skip CHANGE_ME etc.)
)

HISTORY_FINDINGS=0
for pat in "${PATTERNS[@]}"; do
  # Search across all commits; print file:sha for each hit
  HITS=$(git log --all -p --no-color 2>/dev/null \
    | grep -oE "^commit [0-9a-f]{40}|^\+.*${pat}" \
    | grep -v "local-dev-pepper\|generate-a-long-random-\|CHANGE_ME\|ci-test-pepper\|=API_KEY_PEPPER:latest\|=API_KEY_PEPPER=API_KEY_PEPPER\|your-pepper\|not-for-production" \
    | awk '
      /^commit / { sha=substr($2,1,10) }
      /^\+/      { print sha ": " $0 }
    ' | head -5 || true)
  if [[ -n "$HITS" ]]; then
    fail "Pattern '${pat}' found in history:"
    echo "$HITS" | sed 's/^/         /'
    ((HISTORY_FINDINGS++)) || true
  fi
done

[[ $HISTORY_FINDINGS -eq 0 ]] && ok "No secret patterns found in git history"

# ---------------------------------------------------------------------------
# 3. .env.example safety check — must not contain real values
# ---------------------------------------------------------------------------
echo ""
echo "-- Checking .env.example for real values --"

if [[ -f ".env.example" ]]; then
  REAL_VALS=$(grep -E '(API_KEY_PEPPER|E2B_API_KEY|LANGFUSE_SECRET_KEY|PORTAL_JWT_SECRET)=[^#\n]{4,}' \
    .env.example | grep -v '=generate-\|=$\|=<\|=your-\|=pk-\|=sk-\|=e2b_' || true)
  if [[ -n "$REAL_VALS" ]]; then
    warn ".env.example may contain real secret values:"
    echo "$REAL_VALS" | sed 's/^/         /'
  else
    ok ".env.example looks clean (placeholder values only)"
  fi
else
  warn ".env.example not found"
fi

# ---------------------------------------------------------------------------
# 4. terraform.tfvars not tracked
# ---------------------------------------------------------------------------
echo ""
echo "-- Checking terraform.tfvars not tracked --"

if git ls-files infra/terraform/terraform.tfvars 2>/dev/null | grep -q .; then
  fail "infra/terraform/terraform.tfvars is tracked by git — contains secrets, must be gitignored"
else
  ok "terraform.tfvars not tracked"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Summary: $FINDINGS finding(s) ==="

if [[ $FINDINGS -eq 0 ]]; then
  echo -e "${GREEN}All checks passed.${NC}"
  exit 0
elif $STRICT; then
  echo -e "${RED}Findings detected. Aborting (--strict mode).${NC}"
  exit 1
else
  echo -e "${YELLOW}Findings detected. Review above before pushing to GitHub.${NC}"
  exit 0
fi
