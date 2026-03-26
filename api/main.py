"""FastAPI application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from graph.pipeline import dispose_compiled_query_graph
from memory.checkpointer import dispose_checkpoint_pool
from memory.database import database_url, ping_postgres, ping_redis
from memory.redis_client import close_redis
from memory.session import dispose_engine
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.rate_limit import limiter
from api.routes import query as query_routes
from api.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await dispose_compiled_query_graph()
        await dispose_checkpoint_pool()
        await dispose_engine()
        await close_redis()


app = FastAPI(title="querymesh", version="0.1.0", lifespan=lifespan)


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
app.include_router(query_routes.router)


@limiter.exempt
@app.get("/health")
async def health() -> dict:
    """Liveness + dependency status (spec §8 API)."""
    db_url = database_url()
    pg_ok = await ping_postgres(db_url) if db_url else False
    redis_url = os.environ.get("REDIS_URL")
    redis_ok = await ping_redis(redis_url) if redis_url else False
    return {
        "status": "ok",
        "services": {
            "qdrant": False,
            "redis": redis_ok,
            "postgres": pg_ok,
        },
    }
