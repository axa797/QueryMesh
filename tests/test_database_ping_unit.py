"""Unit tests for dependency ping helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from memory import database


def test_ping_qdrant_success() -> None:
    fake_client = MagicMock()
    fake_client.get_collections = AsyncMock()
    fake_client.close = AsyncMock()

    with patch("qdrant_client.AsyncQdrantClient", return_value=fake_client):
        ok = asyncio.run(database.ping_qdrant("http://localhost:6333", api_key=None))

    assert ok is True
    fake_client.get_collections.assert_awaited_once()
    fake_client.close.assert_awaited_once()


def test_ping_qdrant_failure_returns_false() -> None:
    fake_client = MagicMock()
    fake_client.get_collections = AsyncMock(side_effect=OSError("down"))
    fake_client.close = AsyncMock()

    with patch("qdrant_client.AsyncQdrantClient", return_value=fake_client):
        ok = asyncio.run(database.ping_qdrant("http://localhost:6333"))

    assert ok is False
    fake_client.close.assert_awaited_once()
