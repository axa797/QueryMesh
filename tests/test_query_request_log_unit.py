import json

from observability.query_request_log import log_query_request


def test_log_query_request_emits_single_json_line(capsys) -> None:
    log_query_request(
        route="/query",
        method="POST",
        http_status=200,
        latency_ms=42,
        intent_bucket="retrieval",
    )
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    row = json.loads(out[0])
    assert row["message_type"] == "querymesh_query"
    assert row["http_status"] == 200
    assert row["latency_ms"] == 42
    assert row["intent_bucket"] == "retrieval"
