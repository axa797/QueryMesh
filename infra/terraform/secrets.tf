# Derived secrets — schemas owned by terraform, values reconciled by
# cloudbuild.tf.yaml on every tf-apply so they stay in lockstep with the
# resource identifiers below.
#
# If apply returns 409 because a secret already exists (e.g. partial apply), import:
#   terraform import 'google_secret_manager_secret.derived["QDRANT_URL"]' projects/PROJECT_ID/secrets/QDRANT_URL
#
# - DATABASE_URL = postgresql+asyncpg://{user}:{DB_PASSWORD}@/{db}?host=/cloudsql/{connection_name}
# - REDIS_URL    = redis://{redis_host}:{redis_port}/0
# - QDRANT_URL   = {google_cloud_run_v2_service.qdrant.uri}
#
# These are kept as Secret Manager secrets (rather than plain Cloud Run env vars)
# because DATABASE_URL contains the DB password and QDRANT_URL is consumed by
# both the API and the ingest Cloud Build step.

locals {
  derived_secrets = toset([
    "DATABASE_URL",
    "REDIS_URL",
    "QDRANT_URL",
  ])
}

resource "google_secret_manager_secret" "derived" {
  for_each = local.derived_secrets

  project   = var.project_id
  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Grant the build/run SA access to the derived secrets.
# local.cr_sa is defined in iam.tf (Compute Engine default SA — same SA that
# Cloud Build triggers run as and that Cloud Run uses at runtime).
resource "google_secret_manager_secret_iam_member" "derived_accessor" {
  for_each = local.derived_secrets

  project   = var.project_id
  secret_id = google_secret_manager_secret.derived[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cr_sa}"
}

resource "google_secret_manager_secret_iam_member" "derived_version_adder" {
  for_each = local.derived_secrets

  project   = var.project_id
  secret_id = google_secret_manager_secret.derived[each.value].id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${local.cr_sa}"
}
