from observability.query_intent import intent_bucket_from_graph_out


def test_intent_bucket_sorted_from_orchestrator() -> None:
    assert (
        intent_bucket_from_graph_out(
            {
                "orchestrator": {
                    "intents": ["analytics", "retrieval"],
                },
            }
        )
        == "analytics,retrieval"
    )


def test_intent_bucket_unknown_when_missing() -> None:
    assert intent_bucket_from_graph_out({}) == "unknown"
    assert intent_bucket_from_graph_out({"orchestrator": {}}) == "unknown"
