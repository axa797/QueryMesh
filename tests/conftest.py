"""Pytest defaults: avoid requiring Redis for slowapi in unit tests unless overridden."""

from __future__ import annotations

import os

# Phase 14: per-key limits use limits library storage; memory:// keeps pytest hermetic.
os.environ.setdefault("RATE_LIMIT_STORAGE_URI", "memory://")
# Many tests POST /query; a developer .env with a tight limit causes unrelated 429s.
os.environ["QUERY_RATE_LIMIT"] = "10000/minute"
