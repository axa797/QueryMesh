# IAM bindings for Cloud Build SA and Cloud Run default SA.
# Secret values are granted per-secret in bootstrap_gcp.sh; project-level roles here.
#
# Applying this requires permission to set project IAM. Cloud Build runs tf-apply as the
# trigger service account (see bootstrap_gcp.sh: Compute default SA), not the legacy
# *@cloudbuild.gserviceaccount.com address — grant that SA projectIamAdmin (bootstrap does).
# If you see 403 "Policy update access denied", fix grants on the build SA, not cloudbuild@.

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.project.number
  cb_sa          = "${local.project_number}@cloudbuild.gserviceaccount.com"
  cr_sa          = "${local.project_number}-compute@developer.gserviceaccount.com"
}

# Cloud Build SA roles
resource "google_project_iam_member" "cb_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${local.cb_sa}"
}

resource "google_project_iam_member" "cb_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${local.cb_sa}"
}

resource "google_project_iam_member" "cb_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${local.cb_sa}"
}

resource "google_project_iam_member" "cb_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${local.cb_sa}"
}

resource "google_project_iam_member" "cb_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${local.cb_sa}"
}

# Cloud Run default SA roles
resource "google_project_iam_member" "cr_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${local.cr_sa}"
}

resource "google_project_iam_member" "cr_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${local.cr_sa}"
}

resource "google_project_iam_member" "cr_discovery_viewer" {
  project = var.project_id
  role    = "roles/discoveryengine.viewer"
  member  = "serviceAccount:${local.cr_sa}"
}
