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

## 4. Chart and alert

1. **Monitoring** → **Metrics explorer** → search for `querymesh_query` (user-defined log-based metrics).
2. Chart **p50/p95** for the latency distribution (if created).
3. **Alerting** → create policy on:

   - Error rate: filter or label `http_status = 500` (requires labels or a separate error counter metric), or
   - Latency p95 over threshold (align with [spec.md](../spec.md) Phase 2 / observability targets).

## 5. Terraform (optional)

Copy [infra/terraform/log_metrics.tf.example](../infra/terraform/log_metrics.tf.example) into a working Terraform root, set `project_id`, run `terraform plan`. Adjust filters if your `resource.labels.service_name` differs.

## Related

- [infra/README.md](../infra/README.md) — deploy and high-level logging notes.
- [Create log-based metrics](https://cloud.google.com/logging/docs/logs-based-metrics)
