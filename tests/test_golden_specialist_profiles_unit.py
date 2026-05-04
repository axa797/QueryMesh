"""Golden dataset rows stay semantically tied to analytics vs code agents."""

from __future__ import annotations

import re

from evals.golden_loader import load_golden, validate_golden_counts

_ANALYTICS_HINTS = re.compile(
    r"how\s+many|count|metadata|product_area|bigquery|dataset|sql|trend|compare",
    re.IGNORECASE,
)
_CODE_HINTS = re.compile(
    r"\bpython\b|write\s+python|generate\s+code|code\s+sample|snippet|list_buckets",
    re.IGNORECASE,
)


def test_golden_counts_and_categories() -> None:
    rows = load_golden()
    validate_golden_counts(rows)


def test_analytics_rows_imply_bigquery_style_queries() -> None:
    rows = [r for r in load_golden() if r.category == "analytics"]
    assert len(rows) == 10
    failures = [r.id for r in rows if not _ANALYTICS_HINTS.search(r.question)]
    assert not failures, f"analytics rows should mention structured data/SQL idioms: {failures}"


def test_code_generation_rows_imply_code_agent() -> None:
    rows = [r for r in load_golden() if r.category == "code_generation"]
    assert len(rows) == 10
    failures = [r.id for r in rows if not _CODE_HINTS.search(r.question)]
    assert not failures, f"code_generation rows should imply codegen tasks: {failures}"


def test_anchor_ids_exist_for_specialist_smoke() -> None:
    """Stable ids for manual traces: one analytics, one codegen."""
    ids = {r.id for r in load_golden()}
    assert "analytics-01" in ids
    assert "code-01" in ids
