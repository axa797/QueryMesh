# Custom E2B template: Python 3.12 + google-cloud client wheels (no ADC; no egress in runtime).
# Parent image must match current E2B template docs — see scripts/README.md.
# https://e2b.dev/docs/template/quickstart

FROM e2bdev/base:latest

USER user

RUN pip install --user --no-cache-dir \
    "google-cloud-bigquery>=3.41" \
    "google-cloud-storage>=2.14" \
    "google-cloud-run>=0.10" \
    "google-cloud-aiplatform>=1.75"
