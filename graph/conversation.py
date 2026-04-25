"""Format LangGraph message history for LLM prompts (routing, specialists, synthesis)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict, cast

from langchain_core.messages import BaseMessage, HumanMessage


def _stringify_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _role_label(message: BaseMessage) -> str:
    mt = getattr(message, "type", None)
    if mt == "human":
        return "User"
    if mt == "ai":
        return "Assistant"
    return message.__class__.__name__


def format_messages_compact(
    messages: Sequence[BaseMessage],
    *,
    max_messages: int,
) -> str:
    """Last ``max_messages`` chat messages as compact 'User:/Assistant:' lines."""
    if not messages or max_messages <= 0:
        return ""
    recent = list(messages)[-max_messages:]
    lines: list[str] = []
    for m in recent:
        text = _stringify_content(m.content)
        if len(text) > 4000:
            text = text[:3999] + "…"
        lines.append(f"{_role_label(m)}: {text}")
    return "\n".join(lines)


class _MessagesStateLike(TypedDict, total=False):
    messages: list[BaseMessage]


def prior_messages_for_prompt(
    state: dict[str, Any] | _MessagesStateLike,
) -> list[BaseMessage]:
    """All messages before the latest human turn (the current user query)."""
    msgs = cast(list[BaseMessage] | None, state.get("messages"))
    if not msgs:
        return []
    last = msgs[-1]
    if isinstance(last, HumanMessage):
        return list(msgs[:-1])
    return list(msgs)
