#!/usr/bin/env bash
# Download a starter set of public Google Cloud PDFs into corpus/gcp_docs/.
# Sources: docs.cloud.google.com static assets, cloud.google.com/files, services.google.com whitepapers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/corpus/gcp_docs}"
mkdir -p "$DEST"

fetch() {
  local url="$1"
  local name="$2"
  echo "Fetching $name ..."
  curl -fsSL "$url" -o "$DEST/$name"
}

# CLI reference (small)
fetch "https://docs.cloud.google.com/sdk/docs/images/gcloud-cheat-sheet.pdf" \
  "gcloud-cheat-sheet.pdf"

# Architecture, data, AI / RAG-ish (curated; see cloud.google.com/whitepapers/)
fetch "https://services.google.com/fh/files/misc/google_cloud_adoption_framework_whitepaper.pdf" \
  "google-cloud-adoption-framework.pdf"
fetch "https://services.google.com/fh/files/misc/ai_adoption_framework_whitepaper.pdf" \
  "ai-adoption-framework.pdf"
fetch "https://services.google.com/fh/files/misc/improve_llm_performance_reliability.pdf" \
  "improve-llm-performance-rag-customization.pdf"
fetch "https://services.google.com/fh/files/misc/19092_bigquery_best_practices_and_cost_optimization_whitepaper_v3_ca.pdf" \
  "bigquery-cost-optimization-best-practices.pdf"
fetch "https://services.google.com/fh/files/misc/building-a-data-lakehouse.pdf" \
  "building-a-data-lakehouse.pdf"
fetch "https://services.google.com/fh/files/misc/googlecloud_unified_analytics_data_platform_paper_2021.pdf" \
  "unified-analytics-data-platform.pdf"
fetch "https://services.google.com/fh/files/misc/guide_to_google_cloud_databases.pdf" \
  "guide-to-google-cloud-databases.pdf"
fetch "https://services.google.com/fh/files/misc/microservices_on_cloudsql_whitepaper.pdf" \
  "microservices-cloudsql-architecture.pdf"
fetch "https://cloud.google.com/files/kubernetes-your-hybrid-cloud-strategy.pdf" \
  "kubernetes-hybrid-cloud-strategy.pdf"
fetch "https://services.google.com/fh/files/misc/gke_flat_network_design_recommendation.pdf" \
  "gke-flat-network-design.pdf"
fetch "https://services.google.com/fh/files/misc/principles_best_practices_for_data-governance.pdf" \
  "data-governance-principles.pdf"
fetch "https://services.google.com/fh/files/misc/designing_cloud_teams.pdf" \
  "designing-cloud-teams.pdf"
fetch "https://cloud.google.com/files/guide-to-financial-governance.pdf" \
  "guide-to-financial-governance.pdf"
fetch "https://cloud.google.com/dataflow/pdf/TransformingOptionsMarketData.pdf" \
  "dataflow-transforming-options-market-data.pdf"
fetch "https://services.google.com/fh/files/misc/vpc_flow_logs_understanding_byte_and_packet_counts.pdf" \
  "vpc-flow-logs-byte-packet-counts.pdf"

echo "Done. PDFs in $DEST ($(ls -1 "$DEST" | wc -l | tr -d ' ') files)."
echo "Next: set INGESTION_GCP_DOCS_DIR=$DEST (or ./corpus/gcp_docs), run POST /ingest or ingestion CLI — see docs/corpus_runbook.md"
