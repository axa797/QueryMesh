"""Postgres long-term memory reads (spec §7 — read policy before orchestrator)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Spec §7: k=5, 256-token injection budget (hard truncate).
DEFAULT_K = 5
DEFAULT_TOKEN_BUDGET = 256


@dataclass(frozen=True)
class MemoryRow:
    id: UUID
    memory_type: str
    content: str


# preference → context → history (ordering in SQL).

async def load_top_k_memories(
    session: AsyncSession,
    user_internal_id: UUID,
    *,
    k: int = DEFAULT_K,
) -> list[MemoryRow]:
    """Fetch up to ``k`` rows ordered by type priority then ``last_accessed`` DESC."""
    result = await session.execute(
        text(
            """
            SELECT id, memory_type, content
            FROM user_memory
            WHERE user_id = :uid
            ORDER BY
                CASE memory_type
                    WHEN 'preference' THEN 0
                    WHEN 'context' THEN 1
                    WHEN 'history' THEN 2
                    ELSE 3
                END ASC,
                last_accessed DESC NULLS LAST,
                created_at DESC
            LIMIT :k
            """
        ),
        {"uid": user_internal_id, "k": k},
    )
    rows: list[MemoryRow] = []
    for row in result.mappings().all():
        rows.append(
            MemoryRow(
                id=row["id"],
                memory_type=row["memory_type"],
                content=row["content"],
            ),
        )
    return rows


def compact_to_token_budget(
    rows: list[MemoryRow],
    *,
    max_tokens: int = DEFAULT_TOKEN_BUDGET,
) -> str:
    """Join row contents and hard-truncate to ``max_tokens`` (whitespace = token heuristic)."""
    block = "\n".join(m.content.strip() for m in rows if m.content.strip())
    words = block.split()
    if not words:
        return ""
    if len(words) <= max_tokens:
        return block
    return " ".join(words[:max_tokens])
