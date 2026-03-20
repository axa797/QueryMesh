"""Unit tests for long-term memory compaction."""

from __future__ import annotations

import uuid

from memory.longterm import MemoryRow, compact_to_token_budget


def test_compact_truncates_words() -> None:
    words = ["w"] * 300
    rows = [MemoryRow(uuid.uuid4(), "preference", " ".join(words))]
    out = compact_to_token_budget(rows, max_tokens=256)
    assert len(out.split()) == 256


def test_compact_joins_rows() -> None:
    a = MemoryRow(uuid.uuid4(), "preference", "alpha beta")
    b = MemoryRow(uuid.uuid4(), "context", "gamma")
    out = compact_to_token_budget([a, b])
    assert "alpha" in out and "gamma" in out
