# Cloud Logging: `/query` log-based metrics (Phase 2)

The API emits **one JSON object per line** on **stdout** after each `POST /query` (see [observability/query_request_log.py](../observability/query_request_log.py)). On **Cloud Run**, these lines usually appear as **`textPayload`** (raw line) unless your logging agent maps them into `jsonPayload` fields. Use the filters below that match **either** shape.

## 1. Verify logs (Logs Explorer)

1. Open [Logs Explorer](https://console.cloud.google.com/logs/query) for your project.
2. Select **Cloud Run Revision** (`resource.type="cloud_run_revision"`) and your **`api`** service (adjust names if yours differ).
3. Run a short time-range query and confirm lines contain `querymesh_query` after hitting `/query`:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="api"
(
  textPayload=~"\"message_type\"\\s*:\\s*\"querymesh_query\""
  OR jsonPayload.message_type="querymesh_query"
)
```

4. Open one log entry: note whether dimensions are under **`textPayload`** (whole JSON string) or parsed **`jsonPayload.*`**.

## 2. Create a counter metric (request volume)

1. In Cloud Console: **Logging** → **Log-based metrics** → **Create metric**.
2. Choose **Counter**.
3. **Name:** `querymesh_query_requests` (or your naming standard).
4. **Filter** (same as above without extra service filter if you prefer):

```text
resource.type="cloud_run_revision"
(
  textPayload=~"\"message_type\"\\s*:\\s*\"querymesh_query\""
  OR jsonPayload.message_type="querymesh_query"
)
```

5. Save. This counts matching log lines (each successful structured log line = one `/query` completion that reached the logger).

## 3. Create a distribution metric (latency_ms)

1. **Create metric** → **Distribution**.
2. **Filter:** same as the counter.
3. **Field name** / **value extractor** depends on UI version:

   - If logs are **structured** (`jsonPayload.latency_ms` present): use extractor for `jsonPayload.latency_ms`.
   - If logs are **only in `textPayload`**, use a **regular expression** on `textPayload`, e.g. extract the first `"latency_ms":<number>` (see [Build a distribution metric from a counter](https://cloud.google.com/logging/docs/logs-based-metrics/charts-and-alerts)).

4. Set bucket boundaries appropriate for milliseconds (e.g. 0–50–100–250–500–1000–2000–5000+).

5. Optional **labels**: add extractors for `intent_bucket` and `http_status` when those fields exist on `jsonPayload`; for `textPayload`-only lines, use **REGEXP_EXTRACT** on the JSON string.

## 4. Charts (Monitoring)

1. **Monitoring** → **Metrics explorer** → search for `querymesh_query` (user-defined log-based metrics).
2. Chart **request rate** from the counter and **p50/p95** from the latency distribution (if created).

## 5. Alerts aligned with code constants

[observability/gcp_monitoring.py](../observability/gcp_monitoring.py) documents spec §12 **targets** (single place to keep numbers in sync with this playbook):

| Constant | Value | Use |
| -------- | ----- | --- |
| `ALERT_API_ERROR_RATE_PCT` | **5** % | Rolling error share of `/query` handler logs |
| `ALERT_API_ERROR_WINDOW_MIN` | **5** min | Rolling window for error-rate condition |
| `ALERT_P95_LATENCY_SEC` | **8** s | p95 **successful** handler latency (8000 ms in JSON logs) |
| `ALERT_CLOUD_RUN_MAX_INSTANCES` | **10** | Cost / scale guardrail (separate metric) |

**Latency alert (p95 > 8 s):**

1. Requires a **distribution** log-based metric on `latency_ms` (section 3), filtered to **`http_status` 200** if you also log failures with large latencies (optional label extractor on `jsonPayload.http_status`).
2. **Alerting** → **Create policy** → **Add condition** → **Threshold** on that metric → **Aggregated across time series** → **Percentile 95** → trigger if **above 8000** (ms) for **5 minutes** (match `ALERT_API_ERROR_WINDOW_MIN` or tune).

**Error share alert (~5% over 5 min):**

1. Create a **second counter** metric, e.g. `querymesh_query_errors`, with the same base filter as section 2 **plus** `http_status=500`, e.g.:

   ```text
   resource.type="cloud_run_revision"
   resource.labels.service_name="api"
   (jsonPayload.message_type="querymesh_query" AND jsonPayload.http_status=500)
   ```

   If you only have `textPayload`, add `OR textPayload=~"\"http_status\"\\s*:\\s*500"` to the line match.

2. In **Metrics explorer** or **Alerting**, use **MQL** or a **ratio-based** condition: rolling counts of `querymesh_query_errors` / `querymesh_query_requests` **> 0.05** over **5m**. (Exact UI path varies; you can also alert when **error count** exceeds a fixed threshold if traffic is steady.)

3. Tune notifications and runbooks to match your SLOs; **E2B / code paths** may legitimately exceed global latency SLO (see [spec.md](../spec.md) §14).

**Instance / cost guardrail:** use Cloud Run metrics (`instance_count`) with threshold tied to `ALERT_CLOUD_RUN_MAX_INSTANCES`.

## 6. Terraform (optional)

Copy [infra/terraform/log_metrics.tf.example](../infra/terraform/log_metrics.tf.example) into a working Terraform root, set `project_id`, run `terraform plan`. Adjust filters if your `resource.labels.service_name` differs. Alert policies are typically created in Console or a separate Terraform module (ratio / MQL).

## Related

- [infra/README.md](../infra/README.md) — deploy and high-level logging notes.
- [observability/gcp_monitoring.py](../observability/gcp_monitoring.py) — metric name conventions + `ALERT_*` constants.
- [Create log-based metrics](https://cloud.google.com/logging/docs/logs-based-metrics)
