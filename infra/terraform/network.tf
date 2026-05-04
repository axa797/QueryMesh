# Serverless VPC Access connector — lets Cloud Run reach Memorystore (private IP).
# Connectors must use a dedicated /28; the default auto-mode subnet is not /28.

resource "google_vpc_access_connector" "connector" {
  name          = var.vpc_connector_name
  project       = var.project_id
  region        = var.region
  network       = "default"
  ip_cidr_range = var.vpc_connector_cidr

  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.apis]
}
