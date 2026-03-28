"""GCP monitoring stubs — no Cloud API calls."""

from __future__ import annotations

from observability import gcp_monitoring as gm


def test_record_http_request_no_op_at_info_level(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    gm.record_http_request(route="/query", method="POST", status_code=200, latency_ms=12)
    assert "metrics_stub" not in caplog.text
