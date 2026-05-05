"""Unit tests for dependency ping helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from memory import database


def test_ping_qdrant_success() -> None:
    fake_resp = MagicMock()
    fake_resp.status_code = 200

    fake_inner = MagicMock()
    fake_inner.get = AsyncMock(return_value=fake_resp)
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(return_value=fake_inner)
    fake_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=fake_cm):
        ok = asyncio.run(database.ping_qdrant("http://localhost:6333", api_key=None))

    assert ok is True
    fake_inner.get.assert_awaited_once()


def test_ping_qdrant_failure_returns_false() -> None:
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock(side_effect=OSError("down"))
    fake_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=fake_cm):
        ok = asyncio.run(database.ping_qdrant("http://localhost:6333"))

    assert ok is False
