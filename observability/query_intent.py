"""Derive coarse routing label for query logs from orchestrator output."""

from __future__ import annotations


def intent_bucket_from_graph_out(graph_out: dict) -> str:
    orch = graph_out.get("orchestrator")
    if isinstance(orch, dict):
        intents = orch.get("intents")
        if isinstance(intents, list) and intents:
            return ",".join(sorted(str(x) for x in intents))
    return "unknown"
