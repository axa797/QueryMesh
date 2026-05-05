output "database_connection_name" {
  description = "Cloud SQL connection name for Cloud Run --add-cloudsql-instances flag"
  value       = google_sql_database_instance.postgres.connection_name
}

output "database_url_template" {
  description = "DATABASE_URL shape for Cloud Run (fill in password from Secret Manager)"
  value       = "postgresql+asyncpg://${var.db_user}:PASSWORD@/${var.db_name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
  sensitive   = false
}

output "redis_host" {
  description = "Memorystore Redis private IP"
  value       = google_redis_instance.redis.host
}

output "redis_port" {
  description = "Memorystore Redis port"
  value       = google_redis_instance.redis.port
}

output "redis_url" {
  description = "REDIS_URL value for Cloud Run env"
  value       = "redis://${google_redis_instance.redis.host}:${google_redis_instance.redis.port}/0"
}

output "qdrant_url" {
  description = "Internal URL of the Qdrant Cloud Run service"
  value       = google_cloud_run_v2_service.qdrant.uri
}

output "vpc_connector_id" {
  description = "VPC connector resource ID for --vpc-connector flag"
  value       = google_vpc_access_connector.connector.id
}

output "deploy_command" {
  description = "Suggested gcloud builds submit _EXTRA_DEPLOY_ARGS (INGESTION_GCP_DOCS_DIR is set in infra/cloudbuild.yaml deploy step — do not duplicate)."
  value = <<-EOT
    gcloud builds submit --config infra/cloudbuild.yaml \
      --substitutions=_EXTRA_DEPLOY_ARGS="
        --set-secrets=API_KEY_PEPPER=API_KEY_PEPPER:latest,E2B_API_KEY=E2B_API_KEY:latest,DATABASE_URL=DATABASE_URL:latest,REDIS_URL=REDIS_URL:latest,QDRANT_URL=QDRANT_URL:latest,QDRANT_API_KEY=QDRANT_API_KEY:latest,LANGFUSE_PUBLIC_KEY=LANGFUSE_PUBLIC_KEY:latest,LANGFUSE_SECRET_KEY=LANGFUSE_SECRET_KEY:latest,INGEST_TOKEN=INGEST_TOKEN:latest,PORTAL_JWT_SECRET=PORTAL_JWT_SECRET:latest
        --add-cloudsql-instances=${google_sql_database_instance.postgres.connection_name}
        --vpc-connector=${google_vpc_access_connector.connector.name}
        --vpc-egress=private-ranges-only
        --no-cpu-throttling
        --set-env-vars=GOOGLE_CLOUD_PROJECT=${var.project_id},GOOGLE_CLOUD_LOCATION=${var.region},QDRANT_COLLECTION=gcp_docs,RAG_VERTEX_RERANK=true,BIGQUERY_PROJECT_ID=${var.project_id},BIGQUERY_DATASET=querymesh,CORS_ALLOW_ORIGINS=https://query-mesh.vercel.app,CORS_ALLOW_ORIGIN_REGEX=https://.*\\.vercel\\.app,LANGFUSE_HOST=https://us.cloud.langfuse.com
      "
  EOT
}
