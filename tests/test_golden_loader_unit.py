"""Golden eval dataset schema (fast PR gate)."""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.golden_loader import golden_dataset_path, load_golden, validate_golden_counts


def test_golden_dataset_exists() -> None:
    p = golden_dataset_path()
    assert p.is_file(), f"missing {p}"


def test_golden_loads_and_counts() -> None:
    rows = load_golden()
    validate_golden_counts(rows)
    assert rows[0].id.startswith("ret-")


def test_golden_rejects_bad_category(tmp_path: Path) -> None:
    bad = tmp_path / "x.json"
    bad.write_text('[{"id":"a","category":"nope","question":"q","reference_answer":"r"}]')
    with pytest.raises(ValueError, match="invalid category"):
        load_golden(bad)
