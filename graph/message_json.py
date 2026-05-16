"""Serialize LangGraph checkpoint messages for browser/API history."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from graph.conversation import _stringify_content

# Client payload guard; aligns with orchestrator compaction scale.
CONTENT_CHAR_CAP = 8000


def _role_for_message(message: BaseMessage) -> Literal["user", "assistant", "tool"] | None:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    mt = getattr(message, "type", None)
    if mt == "human":
        return "user"
    if mt == "ai":
        return "assistant"
    if mt == "tool":
        return "tool"
    return None


def serialize_messages_for_history(
    messages: list[BaseMessage] | None,
    *,
    content_cap: int = CONTENT_CHAR_CAP,
) -> list[dict[str, Any]]:
    """Turn checkpoint messages into JSON-safe `{role, content}` rows for the UI."""
    if not messages:
        return []
    out: list[dict[str, Any]] = []
    for m in messages:
        role = _role_for_message(m)
        if role is None:
            continue
        text = _stringify_content(m.content)
        if len(text) > content_cap:
            text = text[: content_cap - 1] + "…"
        row: dict[str, Any] = {"role": role, "content": text}
        if role == "assistant":
            ak = getattr(m, "additional_kwargs", None) or {}
            if isinstance(ak, dict):
                cards = ak.get("source_cards")
                if isinstance(cards, list) and cards:
                    row["source_cards"] = cards
        out.append(row)
    return out
