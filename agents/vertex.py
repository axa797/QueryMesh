"""Shared Vertex AI GenAI client for agents (single process cache)."""

from __future__ import annotations

from functools import lru_cache

from google import genai


@lru_cache(maxsize=8)
def vertex_client(project: str, location: str) -> genai.Client:
    return genai.Client(vertexai=True, project=project, location=location)
