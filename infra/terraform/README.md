# Terraform: log-based metrics (optional)

Example resources for **Cloud Logging** metrics driven by [querymesh `/query` JSON logs](../../observability/query_request_log.py).

## Prereqs

- [Google Terraform provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs) configured (`google` provider block in your root module).
- Cloud Run service name in the filter must match production (default below: **`api`**).

## Usage

1. Copy `log_metrics.tf.example` into your root module (e.g. as `log_metrics.tf`) or paste its `resource` blocks into an existing stack.
2. Set `var.project_id` (or replace with a literal `project = "my-project"`).
3. `terraform plan` / `terraform apply`.

**Note:** If stdout lines are stored only in `textPayload`, add a `textPayload=~` clause to the filter (see [docs/cloud_logging_metrics.md](../../docs/cloud_logging_metrics.md)). Redeploy after changing filters.

## Console-first path

If you prefer not to use Terraform, follow the click-path in [docs/cloud_logging_metrics.md](../../docs/cloud_logging_metrics.md).
