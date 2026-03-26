"""slowapi limiter: per API key, Redis-backed storage (spec §8, Phase 14)."""

from __future__ import annotations

import hashlib
import logging

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.settings import get_settings

log = logging.getLogger(__name__)


def _authorization_rate_limit_key(request: Request) -> str:
    """
    Partition limits by Bearer material; fall back to client IP when no credential.
    """
    h1 = request.headers.get("Authorization") or ""
    h2 = request.headers.get("authorization") or ""
    auth = (h1 or h2).strip()
    if auth.lower().startswith("bearer ") and len(auth) > len("bearer "):
        digest = hashlib.sha256(auth.encode("utf-8")).hexdigest()
        return f"apikey:{digest}"
    return f"ip:{get_remote_address(request)}"


def _storage_uri() -> str:
    s = get_settings()
    uri = (s.rate_limit_storage_uri or "").strip()
    if uri:
        return uri
    return s.redis_url


def query_rate_limit_rule() -> str:
    return (get_settings().query_rate_limit or "60/minute").strip()


def build_limiter() -> Limiter:
    uri = _storage_uri()
    common = dict(
        key_func=_authorization_rate_limit_key,
        headers_enabled=True,
        swallow_errors=False,
        strategy="fixed-window",
        default_limits=[query_rate_limit_rule],
    )
    try:
        return Limiter(storage_uri=uri, **common)
    except Exception:
        log.exception("Rate limiter storage init failed; falling back to memory://")
        return Limiter(storage_uri="memory://", **common)


limiter = build_limiter()
