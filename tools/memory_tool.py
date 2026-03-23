"""`save_memory` tool — invoked only from the synthesizer (spec §6.5, §7)."""

from __future__ import annotations

from uuid import UUID

from memory.longterm import insert_user_memory
from sqlalchemy.ext.asyncio import AsyncSession


async def save_memory(
    session: AsyncSession,
    user_internal_id: UUID,
    *,
    memory_type: str,
    content: str,
) -> UUID:
    """Persist long-term memory for ``user_internal_id`` (preference | context | history)."""
    return await insert_user_memory(
        session,
        user_internal_id,
        memory_type=memory_type,
        content=content,
    )
