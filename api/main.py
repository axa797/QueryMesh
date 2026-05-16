"""FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from graph.pipeline import dispose_compiled_query_graph
from memory.checkpointer import dispose_checkpoint_pool
from memory.database import ping_postgres, ping_qdrant, ping_redis
from memory.redis_client import close_redis
from memory.session import dispose_engine
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.rate_limit import limiter
from api.routes import account as account_routes
from api.routes import eval_reports as eval_reports_routes
from api.routes import ingest as ingest_routes
from api.routes import query as query_routes
from api.runtime_info import build_capabilities, log_startup_capabilities
from api.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    log_startup_capabilities(settings)
    try:
        yield
    finally:
        await dispose_compiled_query_graph()
        await dispose_checkpoint_pool()
        await dispose_engine()
        await close_redis()


app = FastAPI(title="querymesh", version="0.1.0", lifespan=lifespan)


def _configure_cors(application: FastAPI) -> None:
    settings = get_settings()
    raw = (settings.cors_allow_origins or "").strip()
    regex = (settings.cors_allow_origin_regex or "").strip()
    if not raw and not regex:
        return
    origins = (
        ["*"] if raw == "*" else ([o.strip() for o in raw.split(",") if o.strip()] if raw else [])
    )
    if raw and raw != "*" and not origins:
        return
    kwargs: dict = {
        "allow_origins": origins,
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "Accept"],
    }
    if regex:
        kwargs["allow_origin_regex"] = regex
    application.add_middleware(CORSMiddleware, **kwargs)


@app.exception_handler(HTTPException)
async def stable_json_errors(request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail and "message" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return await http_exception_handler(request, exc)


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded_json(request: Request, exc: RateLimitExceeded):
    """Stable 429 shape (spec §8)."""
    rule = get_settings().query_rate_limit
    response = JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": f"Too many requests for this API key (limit {rule}).",
        },
    )
    return request.app.state.limiter._inject_headers(
        response,
        getattr(request.state, "view_rate_limit", None),
    )


app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
_configure_cors(app)
app.include_router(account_routes.router)
app.include_router(query_routes.router)
app.include_router(ingest_routes.router)
app.include_router(eval_reports_routes.router)


@limiter.exempt
@app.get("/health")
async def health() -> dict:
    """Liveness + dependency status (spec §8 API)."""
    settings = get_settings()
    db_url = settings.database_url
    pg_ok = await ping_postgres(db_url) if db_url else False
    redis_url = settings.redis_url
    redis_ok = await ping_redis(redis_url) if redis_url else False
    qdrant_ok = await ping_qdrant(
        settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )
    # Frontend treats status != "ok" (or postgres/redis false) as offline — e.g. parked Cloud SQL.
    ready = pg_ok and redis_ok
    payload: dict = {
        "status": "ok" if ready else "degraded",
        "services": {
            "qdrant": qdrant_ok,
            "redis": redis_ok,
            "postgres": pg_ok,
        },
        "capabilities": build_capabilities(settings),
    }
    # Deploy fingerprints (set in infra/cloudbuild.yaml deploy step)
    build_id = os.environ.get("QUERYMESH_BUILD_ID")
    if build_id:
        payload["deploy_build_id"] = build_id
    # Cloud Run–injected env
    revision = os.environ.get("K_REVISION")
    service = os.environ.get("K_SERVICE")
    if revision:
        payload["cloud_run_revision"] = revision
    if service:
        payload["cloud_run_service"] = service
    return payload
