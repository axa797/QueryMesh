#!/usr/bin/env bash
# Bring up local Postgres, Redis, Qdrant and ensure corpus dir exists.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p corpus/gcp_docs
docker compose -f infra/docker-compose.yml up -d
echo "Local deps are up. Next:"
echo "  cp .env.example .env   # then edit API_KEY_PEPPER, optional GOOGLE_CLOUD_PROJECT"
echo "  uv sync && uv run --env-file .env alembic upgrade head"
echo "  PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py"
echo "  PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000"
echo "Open demo/querymesh-demo.html after setting CORS_ALLOW_ORIGINS in .env"
