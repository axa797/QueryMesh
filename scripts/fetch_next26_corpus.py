#!/usr/bin/env python3
"""Fetch Google Cloud Next '26 blog posts and announcement pages into text for corpus/ingest.

Google Cloud Next '26 took place in Las Vegas, April 22–24 2026. This script fetches all
~69 fetchable pages from the 260-announcement wrap-up (blog posts + doc pages) and writes
them as ``.md`` text files into ``corpus/gcp_docs/``.

Use ``--clean`` to delete existing corpus files before fetching (full replacement).

Respectful defaults: ``User-Agent`` identifies the client; ``--delay`` spaces HTTP GETs.

Usage (repo root)::

    # Full replacement (delete old files, fetch all 69 pages):
    PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py --clean

    # Fetch only (add/overwrite without deleting):
    PYTHONPATH=. uv run python scripts/fetch_next26_corpus.py

After running, drop the old Qdrant collection and re-index::

    # Option A — drop via Qdrant REST API (no API server needed):
    curl -sS -X DELETE "http://localhost:6333/collections/gcp_docs" | jq .

    # Option B — let the ingest pipeline drop it (set in .env):
    INGESTION_RECREATE_COLLECTION=true

    # Then trigger ingest (API must be running):
    curl -sS -X POST "$BASE_URL/ingest" \\
      -H "Authorization: Bearer $API_KEY" \\
      -H "Content-Type: application/json" \\
      -d '{"source":"gcp_docs"}'

See docs/corpus_runbook.md for the full step-by-step sequence.

Requires network access.
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "querymesh-corpus-fetch/1.0 (+local RAG index; single-user)"

# 69 pages — all fetchable cloud.google.com/blog/, docs.cloud.google.com/, and
# firebase.blog/ URLs from the Google Cloud Next '26 260-announcement wrap-up.
# Tuple: (URL, output_filename, product_label)
PAGES: list[tuple[str, str, str]] = [
    # ── Next '26 keynote and recap blogs ────────────────────────────────────────────────
    (
        "https://cloud.google.com/blog/topics/google-cloud-next/next26-day-1-recap",
        "next26-day1-keynote-recap.md",
        "Google Cloud Next '26 — Day 1 Keynote Recap",
    ),
    (
        "https://cloud.google.com/blog/topics/google-cloud-next/next26-day-2-recap",
        "next26-day2-developer-keynote-recap.md",
        "Google Cloud Next '26 — Day 2 Developer Keynote Recap",
    ),
    (
        "https://cloud.google.com/blog/topics/google-cloud-next/google-cloud-next-2026-wrap-up",
        "next26-260-announcements-wrap-up.md",
        "Google Cloud Next '26 — 260 Announcements Wrap-up",
    ),
    (
        "https://cloud.google.com/blog/topics/startups/startups-are-building-the-agentic-future-with-google-cloud",
        "next26-startups-agentic-future.md",
        "Google Cloud Next '26 — Startups Building the Agentic Future",
    ),
    # ── Gemini Enterprise Agent Platform blogs ───────────────────────────────────────────
    (
        "https://cloud.google.com/blog/products/ai-machine-learning/introducing-gemini-enterprise-agent-platform",
        "next26-gemini-enterprise-agent-platform.md",
        "Gemini Enterprise Agent Platform — Launch Blog",
    ),
    (
        "https://cloud.google.com/blog/products/ai-machine-learning/the-new-gemini-enterprise-one-platform-for-agent-development",
        "next26-gemini-enterprise-unified-platform.md",
        "Gemini Enterprise — One Platform for Agent Development",
    ),
    (
        "https://cloud.google.com/blog/products/ai-machine-learning/whats-new-in-gemini-enterprise",
        "next26-gemini-enterprise-app.md",
        "Gemini Enterprise App — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/ai-machine-learning/partner-built-agents-available-in-gemini-enterprise",
        "next26-partner-agents-gemini-enterprise.md",
        "Partner-Built Agents in Gemini Enterprise — Agent Gallery",
    ),
    # ── AI infrastructure and compute blogs ─────────────────────────────────────────────
    (
        "https://cloud.google.com/blog/products/compute/ai-infrastructure-at-next26",
        "next26-ai-infrastructure-tpu8.md",
        "AI Hypercomputer — TPU 8t/8i and Infrastructure Announcements",
    ),
    (
        "https://cloud.google.com/blog/products/compute/tpu-8t-and-tpu-8i-technical-deep-dive",
        "next26-tpu8t-tpu8i-technical-deep-dive.md",
        "TPU 8t and TPU 8i — Technical Deep Dive",
    ),
    (
        "https://cloud.google.com/blog/topics/hybrid-cloud/google-distributed-cloud-at-next26",
        "next26-google-distributed-cloud.md",
        "Google Distributed Cloud — Next '26 Announcements",
    ),
    (
        "https://cloud.google.com/blog/products/compute/whats-new-in-compute-at-next26",
        "next26-compute-new-instances.md",
        "Compute Engine — New Instances and Features at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/compute/axion-based-n4a-vms-now-in-preview",
        "next26-axion-n4a-vms.md",
        "Google Axion N4A VMs — General Availability",
    ),
    # ── Agentic Data Cloud and databases blogs ───────────────────────────────────────────
    (
        "https://cloud.google.com/blog/products/data-analytics/whats-new-in-the-agentic-data-cloud",
        "next26-agentic-data-cloud.md",
        "Agentic Data Cloud — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/data-analytics/introducing-the-google-cloud-knowledge-catalog",
        "next26-knowledge-catalog.md",
        "Knowledge Catalog — Universal Context Engine Launch",
    ),
    (
        "https://cloud.google.com/blog/products/data-analytics/the-future-of-data-lakehouse-for-the-agentic-era",
        "next26-cross-cloud-lakehouse.md",
        "Cross-Cloud Lakehouse — Future of Data Lakehouse for the Agentic Era",
    ),
    (
        "https://cloud.google.com/blog/products/data-analytics/unveiling-new-bigquery-capabilities-for-the-agentic-era",
        "next26-bigquery-agentic-capabilities.md",
        "BigQuery — New Agentic Capabilities at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/databases/whats-new-for-google-cloud-databases-at-next26",
        "next26-databases.md",
        "Google Cloud Databases — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/databases/introducing-spanner-omni",
        "next26-spanner-omni.md",
        "Spanner Omni — Multi-Cloud Database Launch",
    ),
    (
        "https://cloud.google.com/blog/products/databases/unify-analytical-and-operational-data-for-ai",
        "next26-reverse-etl-bigquery.md",
        "Unify Analytical and Operational Data for AI — Reverse ETL",
    ),
    # ── Application dev, Cloud Run, GKE, Looker, Firebase blogs ─────────────────────────
    (
        "https://cloud.google.com/blog/products/business-intelligence/looker-updates-for-agentic-bi-at-next26",
        "next26-looker-agentic-bi.md",
        "Looker — Agentic BI Updates at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/serverless/whats-new-for-cloud-run-at-next26",
        "next26-cloud-run.md",
        "Cloud Run — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/serverless/cloud-run-supports-nvidia-rtx-6000-pro-gpus-for-ai-workloads",
        "next26-cloud-run-nvidia-rtx-6000.md",
        "Cloud Run — NVIDIA RTX PRO 6000 Blackwell GPU Support",
    ),
    (
        "https://cloud.google.com/blog/products/containers-kubernetes/whats-new-in-gke-at-next26",
        "next26-gke.md",
        "Google Kubernetes Engine (GKE) — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/application-development/gemini-cloud-assist-at-next26",
        "next26-gemini-cloud-assist.md",
        "Gemini Cloud Assist — Next Generation at Next '26",
    ),
    (
        "https://firebase.blog/posts/2026/04/Cloud-Next-2026-announcements",
        "next26-firebase-announcements.md",
        "Firebase — Cloud Next '26 Announcements",
    ),
    (
        "https://firebase.blog/posts/2026/04/cloud-next-2026-ai-logic",
        "next26-firebase-ai-logic.md",
        "Firebase AI Logic — Next '26 New Features",
    ),
    # ── Networking blogs ─────────────────────────────────────────────────────────────────
    (
        "https://cloud.google.com/blog/products/networking/whats-new-in-cloud-networking-at-next26",
        "next26-cloud-networking.md",
        "Cloud Networking — What's New at Next '26",
    ),
    (
        "https://cloud.google.com/blog/products/networking/introducing-virgo-megascale-data-center-fabric",
        "next26-virgo-network.md",
        "Virgo Network — Megascale Data Center Fabric",
    ),
    (
        "https://cloud.google.com/blog/products/networking/introducing-managed-dranet-in-google-kubernetes-engine",
        "next26-dranet-gke.md",
        "DRANET — Managed Accelerator Networking for GKE",
    ),
    # ── Security blogs ───────────────────────────────────────────────────────────────────
    (
        "https://cloud.google.com/blog/products/identity-security/next26-redefining-security-for-the-ai-era-with-google-cloud-and-wiz",
        "next26-agentic-defense-security.md",
        "Agentic Defense — Security at Next '26 with Google Cloud and Wiz",
    ),
    (
        "https://cloud.google.com/blog/products/identity-security/introducing-google-cloud-fraud-defense-the-next-evolution-of-recaptcha",
        "next26-fraud-defense-recaptcha.md",
        "Google Cloud Fraud Defense — Evolution of reCAPTCHA",
    ),
    (
        "https://cloud.google.com/blog/products/identity-security/google-completes-acquisition-of-wiz",
        "next26-wiz-acquisition.md",
        "Google Completes Acquisition of Wiz",
    ),
    (
        "https://cloud.google.com/blog/products/identity-security/next26-announcing-new-partner-supported-workflows-for-google-security-operations",
        "next26-security-operations-partners.md",
        "Google Security Operations — New Partner Workflows at Next '26",
    ),
    # ── Partners and storage blogs ───────────────────────────────────────────────────────
    (
        "https://cloud.google.com/blog/topics/partners/how-google-cloud-partner-ecosystem-is-building-the-agentic-enterprise",
        "next26-partner-ecosystem-agentic.md",
        "Partner Ecosystem — Building the Agentic Enterprise",
    ),
    (
        "https://cloud.google.com/blog/topics/partners/sap-partnership-unified-data-foundation-zero-copy-sharing-agentic-business-engagement-cloud",
        "next26-sap-unified-data-foundation.md",
        "SAP Partnership — Unified Data Foundation and Zero-Copy Sharing",
    ),
    (
        "https://cloud.google.com/blog/topics/partners/the-foundation-for-the-agentic-enterprise-built-with-oracle-database-at-google-cloud",
        "next26-oracle-database-at-google-cloud.md",
        "Oracle Database at Google Cloud — Agentic Enterprise Foundation",
    ),
    (
        "https://cloud.google.com/blog/products/storage-data-transfer/next26-storage-announcements",
        "next26-storage.md",
        "Google Cloud Storage — Next '26 Announcements",
    ),
    # ── Agent Platform doc pages ─────────────────────────────────────────────────────────
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk",
        "next26-geap-adk.md",
        "Agent Development Kit (ADK)",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-studio/overview",
        "next26-geap-agent-studio.md",
        "Agent Studio",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/agent-garden",
        "next26-geap-agent-garden.md",
        "Agent Garden — Pre-built Agent Templates",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-overview",
        "next26-geap-agent-sandbox.md",
        "Agent Sandbox — Secure Code Execution",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
        "next26-geap-memory-bank.md",
        "Agent Memory Bank",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
        "next26-geap-sessions.md",
        "Agent Sessions",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/assign-identity-iam",
        "next26-geap-agent-identity-iam.md",
        "Agent Identity — IAM and Authorization Policies",
    ),
    (
        "https://docs.cloud.google.com/agent-registry/overview",
        "next26-geap-agent-registry.md",
        "Agent Registry",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview",
        "next26-geap-agent-gateway.md",
        "Agent Gateway",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/view-security-findings",
        "next26-geap-security-threat-detection.md",
        "Agent Security — Threat Detection and Security Findings",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
        "next26-geap-agent-simulation.md",
        "Agent Simulation — Pre-deployment Testing",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
        "next26-geap-agent-evaluation.md",
        "Agent Evaluation and Observability",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
        "next26-geap-agent-optimizer.md",
        "Agent Optimizer — Automated Prompt Refinement",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/long-running-operations",
        "next26-geap-long-running-agents.md",
        "Long-Running Agents — Multi-day Autonomous Operations",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
        "next26-geap-agent-observability.md",
        "Agent Observability",
    ),
    # ── Infrastructure and storage doc pages ─────────────────────────────────────────────
    (
        "https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox",
        "next26-gke-agent-sandbox.md",
        "GKE Agent Sandbox — Isolated AI Agent Runtimes",
    ),
    (
        "https://docs.cloud.google.com/compute/docs/disks/hyperdisks",
        "next26-hyperdisk-overview.md",
        "Hyperdisk — Overview and Types",
    ),
    (
        "https://docs.cloud.google.com/compute/docs/disks/hd-types/hyperdisk-ml",
        "next26-hyperdisk-ml.md",
        "Hyperdisk ML — AI Storage Performance",
    ),
    (
        "https://docs.cloud.google.com/compute/docs/disks/hyperdisk-exapools",
        "next26-hyperdisk-exapools.md",
        "Hyperdisk Exapools — Large-scale AI Training Storage",
    ),
    (
        "https://docs.cloud.google.com/managed-lustre/docs/overview",
        "next26-managed-lustre.md",
        "Google Cloud Managed Lustre — High-throughput File Storage",
    ),
    (
        "https://docs.cloud.google.com/storage/docs/rapid/high-performance-storage",
        "next26-cloud-storage-rapid.md",
        "Cloud Storage Rapid — High-performance Object Storage",
    ),
    (
        "https://docs.cloud.google.com/storage/docs/rapid/rapid-bucket",
        "next26-rapid-bucket.md",
        "Rapid Bucket — Sub-millisecond Latency Object Storage",
    ),
    (
        "https://docs.cloud.google.com/storage/docs/anywhere-cache",
        "next26-rapid-cache.md",
        "Rapid Cache — Accelerated Burst Bandwidth",
    ),
    (
        "https://docs.cloud.google.com/storage/docs/object-contexts",
        "next26-smart-storage-object-contexts.md",
        "Smart Storage — Object Context API",
    ),
    (
        "https://docs.cloud.google.com/storage/docs/use-cloud-storage-mcp",
        "next26-cloud-storage-mcp.md",
        "Cloud Storage MCP Server",
    ),
    # ── MCP, security, and app management doc pages ──────────────────────────────────────
    (
        "https://docs.cloud.google.com/mcp/supported-products",
        "next26-mcp-supported-products.md",
        "MCP Supported Products — Google Cloud MCP Servers",
    ),
    (
        "https://docs.cloud.google.com/model-armor/integrations",
        "next26-model-armor-integrations.md",
        "Model Armor — Integrations with Agent Platform and Firebase",
    ),
    (
        "https://docs.cloud.google.com/saas-runtime/docs/overview",
        "next26-app-lifecycle-manager.md",
        "App Lifecycle Manager — SaaS Runtime Overview",
    ),
    (
        "https://docs.cloud.google.com/unified-maintenance/docs/set-up-unified-maintenance",
        "next26-unified-maintenance.md",
        "Unified Maintenance — App-centric Visibility",
    ),
    (
        "https://docs.cloud.google.com/application-design-center/docs/overview",
        "next26-application-design-center.md",
        "Application Design Center — Natural Language to Deployment",
    ),
]


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", "", html)
    html = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", "", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = re.sub(r"[\t\xa0]+", " ", text)
    text = re.sub(r" +", " ", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n\n".join(lines)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read()
    return body.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("corpus/gcp_docs"),
        help="Output directory (default: corpus/gcp_docs)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help="Seconds to sleep between HTTP requests (default: 0.75)",
    )
    parser.add_argument(
        "--clean",
        "-c",
        action="store_true",
        help=(
            "Delete all existing *.md and *.pdf files in the output directory before fetching. "
            "Use this for a full corpus replacement."
        ),
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.clean:
        to_delete = list(args.out.glob("*.md")) + list(args.out.glob("*.pdf"))
        for f in to_delete:
            f.unlink()
        print(f"Cleaned {len(to_delete)} existing files from {args.out.resolve()}")

    ok = 0
    for i, (url, filename, product_label) in enumerate(PAGES):
        dest = args.out / filename
        try:
            html = _fetch(url)
            text = _html_to_text(html)
            header = (
                f"# Source: {url}\n\n"
                f"_Product: {product_label} — Google Cloud Next '26 corpus export._\n\n"
            )
            dest.write_text(header + text + "\n", encoding="utf-8")
            ok += 1
            print(f"OK  {filename} ({len(text):,} chars)")
        except urllib.error.HTTPError as e:
            print(f"ERR {filename} HTTP {e.code} {url}")
        except urllib.error.URLError as e:
            print(f"ERR {filename} {e.reason!r} {url}")
        if i < len(PAGES) - 1 and args.delay > 0:
            time.sleep(args.delay)

    print(f"\nWrote {ok}/{len(PAGES)} files under {args.out.resolve()}")
    if ok < len(PAGES):
        print("Some pages failed — re-run or add manually; partial corpus still usable.")
    print(
        "\nNext steps (see docs/corpus_runbook.md for full sequence):\n"
        "  1. Drop the Qdrant collection:\n"
        '     curl -sS -X DELETE "http://localhost:6333/collections/gcp_docs" | jq .\n'
        "  2. Start the API and trigger ingest:\n"
        '     curl -sS -X POST "$BASE_URL/ingest" -H "Authorization: Bearer $API_KEY" \\\n'
        '       -H "Content-Type: application/json" -d \'{"source":"gcp_docs"}\'\n'
        "  3. Re-harvest eval data:\n"
        "     PYTHONPATH=. uv run python evals/harvest.py"
    )
    return 0 if ok == len(PAGES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
