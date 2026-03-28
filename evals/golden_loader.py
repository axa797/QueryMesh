"""Load and validate ``golden_dataset.json`` (30 cases: 10×3 categories)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_dataset.json"

_CATEGORIES = frozenset({"retrieval", "code_generation", "analytics"})


@dataclass(frozen=True)
class GoldenRow:
    id: str
    category: str
    question: str
    reference_answer: str
    contexts: list[str]


def golden_dataset_path() -> Path:
    return _GOLDEN_PATH


def load_golden(path: Path | None = None) -> list[GoldenRow]:
    p = path or _GOLDEN_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("golden dataset root must be a list")
    rows: list[GoldenRow] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"row {i}: expected object")
        rid = str(item.get("id") or "").strip()
        cat = str(item.get("category") or "").strip()
        q = str(item.get("question") or "").strip()
        ref = str(item.get("reference_answer") or "").strip()
        ctx_raw = item.get("contexts")
        if not rid or not cat or not q or not ref:
            raise ValueError(f"row {i}: missing id, category, question, or reference_answer")
        if cat not in _CATEGORIES:
            raise ValueError(f"row {i}: invalid category {cat!r}")
        if ctx_raw is None:
            ctxs: list[str] = []
        elif isinstance(ctx_raw, list):
            ctxs = [str(x).strip() for x in ctx_raw if str(x).strip()]
        else:
            raise ValueError(f"row {i}: contexts must be a list")
        rows.append(
            GoldenRow(
                id=rid,
                category=cat,
                question=q,
                reference_answer=ref,
                contexts=ctxs,
            ),
        )
    return rows


def validate_golden_counts(rows: list[GoldenRow]) -> None:
    if len(rows) != 30:
        raise ValueError(f"expected 30 golden rows, got {len(rows)}")
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
    for cat in _CATEGORIES:
        if by_cat.get(cat) != 10:
            raise ValueError(f"expected 10 rows per category {cat!r}, got {by_cat.get(cat, 0)}")
