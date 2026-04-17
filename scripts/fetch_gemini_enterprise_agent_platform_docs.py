#!/usr/bin/env python3
"""Fetch public Gemini Enterprise Agent Platform HTML docs into Markdown-ish text for corpus/ingest.

docs.cloud.google.com does not publish a single PDF bundle for this product; this tool pulls a
curated set of overview/guide pages and writes one ``.md`` file per URL under ``corpus/gcp_docs/``.

Respectful defaults: ``User-Agent`` identifies the client; ``--delay`` spaces HTTP GETs.

Usage (repo root)::

    PYTHONPATH=. uv run python scripts/fetch_gemini_enterprise_agent_platform_docs.py

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

# Curated "major chunk": Build / Scale / Govern / Optimize, models, Agent Registry.
PAGES: list[tuple[str, str]] = [
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/overview",
        "geap-00-platform-overview.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk",
        "geap-01-agent-development-kit.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-studio/overview",
        "geap-02-agent-studio.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/agent-garden",
        "geap-03-agent-garden.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-garden/explore-models",
        "geap-04-model-garden.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-garden/use-models",
        "geap-05-model-garden-use-models.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/rag-overview",
        "geap-06-rag-engine.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/overview",
        "geap-07-vector-search.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale",
        "geap-08-scale-agents-runtime.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
        "geap-09-sessions.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
        "geap-10-memory-bank.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-overview",
        "geap-11-code-execution.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity",
        "geap-12-agent-identity-iam.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview",
        "geap-13-agent-gateway.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/overview",
        "geap-14-governance-policies.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/view-security-findings",
        "geap-15-security-findings.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
        "geap-16-agent-evaluation.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
        "geap-17-simulated-evaluation.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
        "geap-18-observability.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
        "geap-19-optimize-prompts.md",
    ),
    (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start",
        "geap-20-models-api-quickstart.md",
    ),
    (
        "https://docs.cloud.google.com/agent-registry/overview",
        "geap-21-agent-registry.md",
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
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    ok = 0
    for i, (url, filename) in enumerate(PAGES):
        dest = args.out / filename
        try:
            html = _fetch(url)
            text = _html_to_text(html)
            header = (
                f"# Source: {url}\n\n"
                "_Product: Gemini Enterprise Agent Platform — local RAG export._\n\n"
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

    print(f"Wrote {ok}/{len(PAGES)} files under {args.out.resolve()}")
    return 0 if ok == len(PAGES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
