"""Single-line JSON logs for ``/query`` (Phase 2 log-based Cloud Monitoring metrics)."""

from __future__ import annotations

import json
import sys


def log_query_request(
    *,
    route: str,
    method: str,
    http_status: int,
    latency_ms: int,
    intent_bucket: str,
) -> None:
    """Stable one-line JSON for log sinks (see ``infra/README.md``).

    Written to **stdout** as a single JSON object per request so Cloud Run / Cloud Logging can
    parse ``jsonPayload`` when structured JSON detection is enabled.
    """
    payload = {
        "message_type": "querymesh_query",
        "route": route,
        "method": method,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "intent_bucket": intent_bucket,
    }
    print(json.dumps(payload), file=sys.stdout, flush=True)
