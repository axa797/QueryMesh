# Private Service Access for Cloud SQL private IP on the default VPC.
# Required when ipv4_enabled = false (API rejects an instance with no public and no private path).

data "google_compute_network" "default" {
  name    = "default"
  project = var.project_id
}

resource "google_compute_global_address" "private_service_range" {
  name          = "querymesh-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = data.google_compute_network.default.id
  project       = var.project_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = data.google_compute_network.default.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range.name]

  depends_on = [google_project_service.apis]
}
