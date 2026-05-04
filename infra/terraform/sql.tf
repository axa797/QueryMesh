# Cloud SQL — Postgres 16, single-zone (upgrade to HA via settings block for production SLOs).
# DB password is read from Secret Manager (created by bootstrap_gcp.sh, not managed here).

data "google_secret_manager_secret_version" "db_password" {
  project = var.project_id
  secret  = "DB_PASSWORD"
}

resource "google_sql_database_instance" "postgres" {
  name             = var.db_instance_name
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_16"

  settings {
    tier              = "db-g1-small"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = false
    }

    ip_configuration {
      ipv4_enabled = false
      # Cloud Run connects via Unix socket (Cloud SQL Auth Proxy) — no public IP needed.
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }
  }

  deletion_protection = true

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "db" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
}

resource "google_sql_user" "user" {
  name     = var.db_user
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  password = data.google_secret_manager_secret_version.db_password.secret_data
}
