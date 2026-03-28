"""GCP Cloud Monitoring hooks and naming (spec §11–§12, Phase 16).

v1 does not export custom metrics to Cloud Monitoring from this process. Cloud Run already
emits request logs; use **log-based metrics** and **Alerting policies** in the Google Cloud
console from those logs, or add an OpenTelemetry exporter in a later iteration.

This module documents intended custom metric types and emits **debug** lines for local
verification when ``logging`` level is DEBUG.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Suggested custom metric type names after creating a metrics descriptor in GCP
# (prefix with your workspace / domain as required).
METRIC_HTTP_REQUEST_LATENCY_MS = "querymesh/http/request_latency_ms"
METRIC_HTTP_REQUEST_COUNT = "querymesh/http/request_count"
METRIC_AGENT_ERRORS = "querymesh/agent/errors"
METRIC_QDRANT_LATENCY_MS = "querymesh/qdrant/query_latency_ms"
METRIC_REDIS_SESSION_LOOKUP = "querymesh/redis/session_lookups"

# Spec §12 alert thresholds (documentary — configure in Cloud Monitoring UI or Terraform)
ALERT_API_ERROR_RATE_PCT = 5.0
ALERT_API_ERROR_WINDOW_MIN = 5
ALERT_P95_LATENCY_SEC = 8.0
ALERT_CLOUD_RUN_MAX_INSTANCES = 10


def record_http_request(
    *,
    route: str,
    method: str,
    status_code: int,
    latency_ms: int,
) -> None:
    """Structured debug log stub until OTel / custom metrics are wired."""
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "metrics_stub %s %s %s status=%s latency_ms=%s",
            METRIC_HTTP_REQUEST_LATENCY_MS,
            method,
            route,
            status_code,
            latency_ms,
        )
