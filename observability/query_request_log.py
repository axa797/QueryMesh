"""Single-line JSON logs for ``/query`` (Cloud Monitoring log-based metrics)."""

from __future__ import annotations

import json
import sys
from typing import Any


def log_query_request(
    *,
    route: str,
    method: str,
    http_status: int,
    latency_ms: int,
    intent_bucket: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Stable one-line JSON for log sinks (see ``infra/README.md``).

    Written to **stdout** as a single JSON object per request so Cloud Run / Cloud Logging can
    parse ``jsonPayload`` when structured JSON detection is enabled.
    """
    payload: dict[str, Any] = {
        "message_type": "querymesh_query",
        "route": route,
        "method": method,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "intent_bucket": intent_bucket,
    }
    if extra:
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
    print(json.dumps(payload), file=sys.stdout, flush=True)
