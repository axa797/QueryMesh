"""Best-effort parsing of streaming JSON ``message`` for the synthesizer."""

from __future__ import annotations

from agents.synthesizer import provisional_json_message_field


def test_provisional_partial_string() -> None:
    acc = '{"message": "Hello world", "save_me'
    assert provisional_json_message_field(acc) == "Hello world"


def test_provisional_with_escape() -> None:
    acc = '{"message": "Say \\"hi\\"", "x": 1}'
    assert provisional_json_message_field(acc) == 'Say "hi"'
