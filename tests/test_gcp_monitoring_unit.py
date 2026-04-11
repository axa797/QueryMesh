"""GCP monitoring stubs — no Cloud API calls."""

from __future__ import annotations

from observability import gcp_monitoring as gm


def test_alert_constants_match_spec_operational_defaults() -> None:
    """Keep in sync with spec §12 and docs/cloud_logging_metrics.md section 5."""
    assert gm.ALERT_API_ERROR_RATE_PCT == 5.0
    assert gm.ALERT_API_ERROR_WINDOW_MIN == 5
    assert gm.ALERT_P95_LATENCY_SEC == 8.0
    assert gm.ALERT_CLOUD_RUN_MAX_INSTANCES == 10


def test_record_http_request_no_op_at_info_level(caplog) -> None:
    import logging

    caplog.set_level(logging.INFO)
    gm.record_http_request(route="/query", method="POST", status_code=200, latency_ms=12)
    assert "metrics_stub" not in caplog.text
