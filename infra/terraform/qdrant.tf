# Qdrant vector store — self-hosted on Cloud Run.
# min-instances=1 keeps vectors in memory between requests (avoids cold-start data loss).
# API key is read from Secret Manager.

data "google_secret_manager_secret_version" "qdrant_api_key" {
  project = var.project_id
  secret  = "QDRANT_API_KEY"
}

resource "google_cloud_run_v2_service" "qdrant" {
  name     = var.qdrant_service_name
  project  = var.project_id
  location = var.region

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }

    containers {
      image = var.qdrant_image

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
        startup_cpu_boost = true
      }

      env {
        name  = "QDRANT__SERVICE__API_KEY"
        value = data.google_secret_manager_secret_version.qdrant_api_key.secret_data
      }

      ports {
        container_port = 6333
      }

      startup_probe {
        http_get {
          path = "/readyz"
          port = 6333
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Qdrant is protected by QDRANT__SERVICE__API_KEY (header api-key). Cloud Run
# must allow unauthenticated invoke so callers can reach the container; unscoped
# IAM (compute SA only) blocks Cloud Build and curl without a Google ID token.
resource "google_cloud_run_v2_service_iam_member" "qdrant_invoker_all" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.qdrant.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Redundant but documents that the API runtime SA may invoke via IAM if desired.
resource "google_cloud_run_v2_service_iam_member" "qdrant_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.qdrant.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${data.google_compute_default_service_account.default.email}"
}

data "google_compute_default_service_account" "default" {
  project = var.project_id
}
