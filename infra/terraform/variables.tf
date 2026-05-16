variable "project_id" {
  description = "GCP project ID (e.g. querymesh-kb)"
  type        = string
}

variable "region" {
  description = "Primary GCP region"
  type        = string
  default     = "us-central1"
}

variable "db_instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "querymesh-pg"
}

variable "db_name" {
  description = "Postgres database name"
  type        = string
  default     = "querymesh"
}

variable "db_user" {
  description = "Postgres user name"
  type        = string
  default     = "querymesh"
}

variable "redis_instance_name" {
  description = "Memorystore Redis instance name"
  type        = string
  default     = "querymesh-redis"
}

variable "qdrant_service_name" {
  description = "Cloud Run service name for Qdrant"
  type        = string
  default     = "qdrant"
}

variable "api_service_name" {
  description = "Cloud Run service name for the querymesh API"
  type        = string
  default     = "api"
}

variable "vpc_connector_name" {
  description = "Serverless VPC Access connector name"
  type        = string
  default     = "querymesh-connector"
}

variable "vpc_connector_cidr" {
  description = "Unused /28 in the default VPC for the serverless connector (must not overlap region subnets)"
  type        = string
  default     = "10.8.0.0/28"
}

variable "qdrant_image" {
  description = "Qdrant Docker image"
  type        = string
  default     = "qdrant/qdrant:v1.13.4"
}

variable "cors_allow_origins" {
  description = "Comma-separated browser Origins for the FastAPI CORS middleware. Include every production/preview web UI URL the browser uses (e.g. Vercel + Cloud Run web)."
  type        = string
  default     = "https://query-mesh.vercel.app"
}

variable "cors_allow_origin_regex" {
  description = "Optional Starlette allow_origin_regex for CORS (e.g. all *.vercel.app preview deployments). Set to empty string to disable."
  type        = string
  default     = "https://.*\\.vercel\\.app"
}
