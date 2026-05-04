# Memorystore Redis 7 — session envelope + rate-limit storage.
# Basic tier (single node); upgrade to Standard for HA.
# Accessible only via private IP → requires the VPC connector.

resource "google_redis_instance" "redis" {
  name           = var.redis_instance_name
  project        = var.project_id
  region         = var.region
  tier           = "BASIC"
  memory_size_gb = 1
  redis_version  = "REDIS_7_0"
  display_name   = "querymesh session + rate-limit store"

  depends_on = [
    google_project_service.apis,
    google_vpc_access_connector.connector,
  ]
}
