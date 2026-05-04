terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state in GCS — bucket created by scripts/bootstrap_gcp.sh.
  # Init: terraform init -backend-config="bucket=${PROJECT_ID}-tf-state"
  backend "gcs" {
    prefix = "terraform/state"
    # bucket is passed at init time via -backend-config or TF_BACKEND_CONFIG
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
