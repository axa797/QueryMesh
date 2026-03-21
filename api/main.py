"""FastAPI application."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from graph.pipeline import dispose_compiled_query_graph
from memory.checkpointer import dispose_checkpoint_pool
from memory.database import database_url, ping_postgres, ping_redis
from memory.redis_client import close_redis
from memory.session import dispose_engine

from api.routes import query as query_routes


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


app.include_router(query_routes.router)


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
