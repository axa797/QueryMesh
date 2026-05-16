"""LangGraph → API message serialization."""

from __future__ import annotations

from graph.message_json import serialize_messages_for_history
from langchain_core.messages import AIMessage, HumanMessage


def test_human_and_ai_roles() -> None:
    msgs = [
        HumanMessage(content="hello"),
        AIMessage(content="world"),
    ]
    rows = serialize_messages_for_history(msgs)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "hello"
    assert rows[1]["content"] == "world"


def test_empty_and_none() -> None:
    assert serialize_messages_for_history([]) == []
    assert serialize_messages_for_history(None) == []
