"""BigQuery SQL guard (read-only)."""

from __future__ import annotations

import pytest
from tools.bigquery_tool import validate_read_only_sql


def test_accepts_select() -> None:
    s = validate_read_only_sql("SELECT doc_name FROM `p.d.t` WHERE word_count > 100")
    assert "SELECT" in s


def test_accepts_with_cte() -> None:
    s = validate_read_only_sql(
        "WITH a AS (SELECT 1 AS x) SELECT * FROM a",
    )
    assert s.startswith("WITH")


def test_rejects_drop() -> None:
    with pytest.raises(ValueError, match="mutating"):
        validate_read_only_sql("DROP TABLE IF EXISTS t")


def test_rejects_multiple_statements() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        validate_read_only_sql("SELECT 1; SELECT 2")


def test_rejects_insert_select() -> None:
    with pytest.raises(ValueError, match="mutating"):
        validate_read_only_sql("INSERT INTO t SELECT 1")
