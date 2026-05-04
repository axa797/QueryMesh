# querymesh API — Cloud Run. Build from repo root:
#   docker build -f infra/Dockerfile .
#
# Requires runtime env: DATABASE_URL, API_KEY_PEPPER, REDIS_URL, QDRANT_URL,
# GOOGLE_CLOUD_PROJECT (often auto-set on Cloud Run). See infra/README.md.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY api ./api
COPY agents ./agents
COPY graph ./graph
COPY ingestion ./ingestion
COPY memory ./memory
COPY observability ./observability
COPY tools ./tools
COPY evals ./evals
COPY alembic ./alembic
COPY alembic.ini .
# Corpus: pre-fetched markdown files written by scripts/fetch_next26_corpus.py.
# Cloud Build runs that script before docker build; the directory is gitignored locally.
# If the directory is absent (local builds without corpus), ingest will fail gracefully.
COPY corpus/gcp_docs ./corpus/gcp_docs

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
