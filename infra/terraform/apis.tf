# Enable all APIs required by querymesh in production.
# google_project_service is idempotent — safe to apply repeatedly.

locals {
  required_apis = toset([
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "discoveryengine.googleapis.com",
    "vpcaccess.googleapis.com",
    "iam.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
