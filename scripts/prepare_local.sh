#!/usr/bin/env bash
# Bring up local Postgres, Redis, Qdrant, Next.js web (Docker), and ensure corpus dir exists.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p corpus/gcp_docs
docker compose -f infra/docker-compose.yml up -d
echo "Local deps + web UI (Docker on :3000) are up."
echo "Rebuild the web bundle after NEXT_PUBLIC_* or Dockerfile changes:"
echo "  docker compose -f infra/docker-compose.yml up -d --build web"
echo ""
echo "Self-hosted without GCP: in .env leave GOOGLE_CLOUD_PROJECT unset (or empty)."
echo "  API + /query use Docker services + offline/heuristic agents; no gcloud/ADC required."
echo "  Vertex features (smart routing, LLM RAG/synth, embeddings retrieval, /ingest, BigQuery) need a project + ADC."
echo ""
echo "Next:"
echo "  cp .env.example .env   # set API_KEY_PEPPER; add GOOGLE_CLOUD_PROJECT only if using Vertex"
echo "  uv sync && uv run --env-file .env alembic upgrade head"
echo "  PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py"
echo "  PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000"
echo "Open http://localhost:3000 (Next.js via Docker); set CORS_ALLOW_ORIGINS in .env."
echo "  Or demo/querymesh-demo.html with CORS for that origin."
