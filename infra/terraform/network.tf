# Serverless VPC Access connector — lets Cloud Run reach Memorystore (private IP).

resource "google_vpc_access_connector" "connector" {
  name    = var.vpc_connector_name
  project = var.project_id
  region  = var.region

  subnet {
    name = "default"
  }

  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.apis]
}
