# Project 1: Multi-Agent Enterprise Knowledge Assistant

## Technical Specification

**Repository:** querymesh — multi-agent GCP knowledge assistant.

---

## 1. Overview

A multi-agent system that accepts natural language queries and routes them to specialized agents based on intent. An orchestrator classifies each query, delegates to the appropriate agent, and a synthesizer assembles the final structured response.

**Primary goal:** Hands-on experience with multi-agent orchestration, deployment, observability, and evals on a production-grade GCP stack.

**Corpus:** GCP documentation PDFs (publicly available, no procurement needed)

---

## 2. Agent Topology

```
User Query
    │
    ▼
Orchestrator (LangGraph)
    │
    ├── RAG Agent          → searches GCP documentation corpus
    ├── Code Agent         → generates / explains code samples (+ optional E2B execution)
    └── Analytics Agent    → queries structured data in BigQuery
    │
    ▼
Synthesizer
    │
    ▼
Final Response
```

### Agent Responsibilities


| Agent           | Trigger                                        | Input                                              | Output                                                                              |
| --------------- | ---------------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Orchestrator    | Every query                                    | Raw user query + optional long-term memory summary | Classified intent + routed subtasks                                                 |
| RAG Agent       | "what is", "explain", "how does X work"        | Query + retrieval context                          | **Structured JSON** (answer + citations + confidence)                               |
| Code Agent      | "write", "generate", "show me code", "example" | Query + language hint                              | Code block + explanation (+ sandbox stdout/stderr when executed)                    |
| Analytics Agent | "compare", "how many", "trend", "metric"       | Query + BigQuery schema                            | Structured data answer                                                              |
| Synthesizer     | After all delegated agents respond             | Agent outputs                                      | Single coherent **user-facing** response; **only node that may call `save_memory`** |


---

## 3. System Architecture

### Request Flow

```
1. Client sends POST /query with Authorization: Bearer <api_key>
2. Server resolves api_key → user_internal_id (users.id); rate-limit per key (429 if exceeded)
3. Validate session_id binding to user_internal_id; invalid/other-user session → 403
4. If session_id omitted: mint new session_id (still bound to user before persistence)
5. Load top-k long-term memories for user_internal_id; inject compact block before orchestrator
6. Orchestrator classifies intent (single or multi-agent); max 3 specialist fan-outs per query
7. Relevant agent(s) execute in parallel where possible (within fan-out cap)
8. Agent outputs passed to Synthesizer (renders JSON specialists into readable answer)
9. Response returned with trace_id, latency_ms, session_id
10. Full trace logged to Langfuse (hosted in v1)
11. Agent state checkpointed to Postgres via LangGraph Checkpointer (thread_id = f"{user_internal_id}:{session_id}")
12. Redis holds session envelope only (TTL 24h); checkpoint is source of truth for graph state
```

### Data Flow

```
GCP Docs PDFs
    │
    ▼
LlamaIndex Parser (chunked by section; fallback fixed-size + overlap if structure poor — log metric)
    │
    ▼
Vertex AI Embeddings
    │
    ▼
Qdrant (vector store)
    │
    ▼
RAG Agent (retrieval at query time; optional Vertex reranker behind feature flag)
```

---

## 4. Tech Stack


| Layer             | Tool                           | Version / Notes                                                                                                |
| ----------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| LLM               | Gemini 2.5 Pro via Vertex AI   | Primary model for all agents                                                                                   |
| Orchestration     | LangGraph                      | Agent graph, state management, routing                                                                         |
| RAG pipeline      | LlamaIndex                     | Ingestion, chunking, retrieval                                                                                 |
| Vector DB         | Qdrant                         | Self-hosted on Cloud Run                                                                                       |
| Agent state       | LangGraph Checkpointer         | Postgres (same Cloud SQL instance as app tables; namespaced migrations)                                        |
| Session memory    | Redis                          | Cloud Memorystore — **session envelope only**                                                                  |
| Long-term memory  | Cloud SQL (Postgres)           | `user_memory` + identity tables                                                                                |
| Code execution    | E2B                            | Python-only sandbox; **no egress**; pre-baked `google-cloud-`* template; **no GCP credentials inside sandbox** |
| Evals             | RAGAS + DeepEval               | RAG metrics + agent behavior metrics                                                                           |
| LLM Observability | Langfuse                       | **Hosted (SaaS) for v1**; self-hosted Cloud Run deferred (e.g. Project 2 / data residency practice)            |
| Infra monitoring  | Cloud Monitoring               | Latency, error rate, cost                                                                                      |
| API               | FastAPI                        | Async, Python                                                                                                  |
| Rate limiting     | slowapi                        | Per-key limits on `/query`; **Redis-backed** storage (same Memorystore as sessions)                            |
| Deployment        | Cloud Run                      | API + Qdrant; **region: us-central1** for Vertex + Run + BigQuery alignment                                    |
| Jobs              | Cloud Run Jobs                 | **Production ingestion** (`/ingest` triggers job); local uses BackgroundTasks                                  |
| CI/CD             | Cloud Build                    | Auto-deploy on push to main; **PRs run unit tests only**                                                       |
| Secrets           | Secret Manager                 | E2B API key; API-key **pepper** for digest; other sensitive config                                             |
| Tool protocol     | MCP-shaped interfaces          | **Internal registry only in v1** — MCP-compatible contracts for future external server                         |
| Embeddings        | Vertex AI `text-embedding-005` | English/code; `text-embedding-004` retired 2026-01-14                                                           |


### Feature flags


| Flag                | Prod default | Local default | Purpose                         |
| ------------------- | ------------ | ------------- | ------------------------------- |
| `RAG_VERTEX_RERANK` | on           | off           | Vertex reranker after retrieval |


---

## 5. Repository Structure

```
querymesh/
├── agents/
│   ├── orchestrator.py       # Routing + intent JSON; temp=0; retry-on-parse failure
│   ├── rag_agent.py          # LlamaIndex retrieval + structured JSON output
│   ├── code_agent.py         # Code generation + E2B invocation (exclusive caller)
│   ├── analytics_agent.py    # BigQuery tool + response; SQL gen temp=0
│   └── synthesizer.py        # Final assembly + save_memory tool only
├── graph/
│   └── pipeline.py           # LangGraph graph definition + thread_id strategy
├── ingestion/
│   ├── loader.py             # PDF loading with LlamaIndex
│   ├── chunker.py            # Section-aware chunking + fallback splitter
│   └── indexer.py            # Embedding + Qdrant indexing
├── tools/
│   ├── bigquery_tool.py      # BigQuery execution + validation
│   ├── retrieval_tool.py     # Vector retrieval helper (internal MCP shape)
│   ├── code_exec_tool.py     # E2B sandbox runner (internal MCP shape)
│   └── memory_tool.py        # save_memory — exposed only to synthesizer
├── memory/
│   ├── checkpointer.py       # LangGraph Checkpointer config
│   ├── session.py            # Redis session envelope + binding to user_internal_id
│   └── longterm.py           # Postgres long-term memory read/write helpers
├── api/
│   ├── main.py               # FastAPI app + endpoints
│   └── auth.py               # Bearer resolution → user_internal_id (optional split)
├── scripts/
│   └── bootstrap_bq.py       # DDL + deterministic synthetic seed (+ README instructions)
├── evals/
│   ├── golden_dataset.json   # 30 hand-crafted Q&A pairs
│   ├── golden_loader.py      # Load + validate golden JSON
│   ├── ragas_eval.py         # RAGAS evaluation runner
│   └── test_deepeval_suite.py  # DeepEval pytest suite (``eval`` marker)
├── observability/
│   └── instrumentation.py    # Langfuse tracing setup (hosted endpoint)
├── infra/
│   ├── Dockerfile             # API container
│   ├── cloudbuild.yaml        # Build + push + Cloud Run deploy (main)
│   ├── cloudbuild.pr.yaml     # PR / fast pytest
│   ├── README.md              # Deploy, secrets, Qdrant notes
│   └── docker-compose.yml     # Local dev (Qdrant + Redis + Postgres)
└── docs/
    └── architecture.md       # Architecture diagram + decisions
```

---

## 6. Agent Specifications

### 6.1 Orchestrator

**Responsibility:** Classify incoming query, determine which agents to invoke, manage parallel execution where possible (**max 3** concurrent specialists per query).

**Model settings:** `temperature = 0` for routing.

**Structured output handling:** On invalid JSON / schema mismatch → **retry once** with a repair prompt; if still failing → **default to RAG-only** intent and **log** structured failure + trace metadata.

**System prompt:**

```
You are a routing orchestrator. Given a user query, classify it into one or more 
of the following intents: [retrieval, code_generation, analytics]. 

Return a JSON object:
{
  "intents": ["retrieval"],          // one or more
  "rewritten_queries": {             // one per intent, optimized for that agent
    "retrieval": "..."
  },
  "parallel": true                   // whether agents can run concurrently
}
```

**Routing logic:**

- Single intent → route to one agent
- Multiple intents → fan out (≤ 3 specialists), run in parallel where possible, synthesize
- Ambiguous query → default to RAG agent

---

### 6.2 RAG Agent

**Responsibility:** Retrieve relevant context from GCP documentation corpus and produce **structured JSON** (not markdown prose). The synthesizer renders citations for the user.

**Retrieval strategy:**

- Top-k = 5 chunks
- **Vertex AI reranker** when feature flag enabled (prod default on; local default off)
- Each chunk tagged with source document + section
- **Chunking fallback:** If section-aware splits fail (poor PDF structure), use fixed-size chunks with overlap; emit **warning metric/log**

**System prompt:**

```
You are a GCP documentation expert. Answer the user's question using ONLY 
the provided context. For every claim, cite the source document and section.
If the context does not contain enough information, say so explicitly.
Do not hallucinate.
```

**Output format (strict JSON — synthesizer consumes):**

```json
{
  "answer": "...",
  "citations": [
    {"document": "cloud-run-docs.pdf", "section": "Scaling Configuration", "chunk_id": "..."}
  ],
  "confidence": "high | medium | low"
}
```

---

### 6.3 Code Agent

**Responsibility:** Generate, explain, or debug **Python** samples for v1; optionally execute in **E2B** via `code_exec_tool` (**only this agent** invokes the sandbox).

**Model settings:** `temperature = 0` for codegen core paths; **small > 0 allowed only for narrative explanation** steps if needed (keep deterministic defaults elsewhere).

**Sandbox (E2B) policy:**

- **No network egress** from sandbox; **stdlib + pre-installed `google-cloud-*`** on template image only
- **Never** inject GCP ADC / service-account material into the environment
- **Limits:** wall-clock **15s**; combined stdout+stderr capture **64KiB** then truncate with `[truncated]` marker; **max 2 concurrent** sandbox runs per Cloud Run API replica (tune after profiling)

**System prompt:**

```
You are a GCP developer expert. Generate clean, production-ready code samples.
Always specify:
- Language and runtime version
- Required dependencies (must align with sandbox pre-install set when execution is requested)
- Any GCP-specific configuration needed (note: sandbox cannot reach live GCP without external credentials — explain limits)
Include inline comments for non-obvious logic.
```

**Output format:**

```json
{
  "language": "python",
  "code": "...",
  "explanation": "...",
  "dependencies": ["google-cloud-run", "..."],
  "notes": "...",
  "execution": { "stdout": "...", "stderr": "...", "exit_code": 0 }
}
```

*(Omit or null `execution` when execution not requested / skipped.)*

---

### 6.4 Analytics Agent

**Responsibility:** Translate natural language into BigQuery SQL, execute query, return structured results.

**Model settings:** `temperature = 0` for SQL generation.

**BigQuery dataset:** GCP documentation metadata (doc name, section, word count, last updated, product area) — **synthetic but structured**, bootstrapped via `**scripts/bootstrap_bq.py` + README** (Terraform later). Service account uses **least privilege** on the seeded dataset only (`bigquery.jobUser` scoped as tightly as practical).

**System prompt:**

```
You are a BigQuery SQL expert. Translate the user's question into a valid 
BigQuery SQL query against the provided schema. Return only valid SQL.
Do not explain. Do not add markdown.
```

**Tool flow:**

1. LLM generates SQL
2. SQL validated before execution (block DROP, DELETE, UPDATE)
3. BigQuery executes
4. Results formatted and returned

**Output format:**

```json
{
  "sql": "SELECT ...",
  "results": [...],
  "row_count": 12,
  "interpretation": "..."
}
```

---

### 6.5 Synthesizer

**Responsibility:** Combine specialist outputs into one coherent **user-facing** response; **preserve citations** from structured RAG JSON.

**Tools:** `**save_memory(memory_type, content)` only here** — long-term writes are tool-driven, never silent auto-logging.

**System prompt:**

```
You are a response synthesizer. You receive structured outputs from one or more 
specialist agents. Combine them into a single coherent response.
Preserve all citations from structured inputs. Do not add information not present in the agent outputs.
Format for readability — use sections if multiple agents contributed.
```

---

## 7. Memory Architecture

### Three-tier memory model


| Tier             | Store                              | Scope                                        | TTL                                         |
| ---------------- | ---------------------------------- | -------------------------------------------- | ------------------------------------------- |
| Agent state      | LangGraph Checkpointer (Postgres)  | Per `thread_id`                              | Session lifetime / explicit eviction policy |
| Session envelope | Redis (Cloud Memorystore)          | Per `session_id` bound to `user_internal_id` | 24 hours                                    |
| Long-term memory | Cloud SQL Postgres (`user_memory`) | Per user across sessions                     | Indefinite                                  |


**Redis payload (envelope only):** e.g. `{ session_id, user_internal_id, thread_id, optional pointers }` — **do not duplicate LangGraph messages/state** in Redis.

**LangGraph checkpoint key:** `thread_id = "{user_internal_id}:{session_id}"` (opaque UUIDs — delimiter-safe).

### Identity schema (Postgres)

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Issued keys stored as HMAC-SHA256(raw_key, pepper); pepper from Secret Manager / env.
CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  key_digest TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT NOW(),
  revoked_at TIMESTAMP
);

CREATE INDEX idx_api_keys_active ON api_keys(key_digest) WHERE revoked_at IS NULL;
```

### Long-term memory schema

```sql
CREATE TABLE user_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  memory_type TEXT NOT NULL CHECK (memory_type IN ('preference', 'context', 'history')),
  content TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  last_accessed TIMESTAMP
);

CREATE INDEX idx_user_memory_user_id ON user_memory(user_id);
```

### Read policy (every `/query`, before orchestrator)


| Parameter             | Value                                                                                         |
| --------------------- | --------------------------------------------------------------------------------------------- |
| `k`                   | 5 rows fetched                                                                                |
| Injected token budget | **256 tokens** (hard truncate)                                                                |
| Ordering              | Type priority: `**preference` → `context` → `history`**; within type `**last_accessed DESC`** |


### Write policy

- **Tool-only:** `save_memory` callable **only from synthesizer**

---

## 8. API Specification

### Authentication

- Clients authenticate with `**Authorization: Bearer <api_key>`** (only documented mechanism).
- Server computes digest via **HMAC-SHA256(api_key, pepper)** (constant-time compare), resolves `**users.id`** as `**user_internal_id`**.
- `**user_id` is never accepted from the client.**

### Rate limiting

- **60 requests / minute / API key** via **slowapi** with a **Redis** storage backend (no bespoke counter logic).
- **429 Too Many Requests** when exceeded.

### Session semantics

- `**session_id` optional.** If omitted → server mints a new UUID and returns it on every response.
- `**session_id` must belong to the authenticated `user_internal_id`.** Otherwise → **403 Forbidden** with stable error shape (below).

### Errors

403 example (invalid session):

```json
{
  "error": "invalid_session",
  "message": "Session is unknown or does not belong to this API key."
}
```

### Endpoints

```
POST /query
  Headers:  Authorization: Bearer <api_key>
  Request:  { "query": string, "session_id"?: string | null }
  Response: {
    "response": object | string,
    "trace_id": string,
    "latency_ms": int,
    "session_id": string
  }

GET /health
  Response: { "status": "ok", "services": { "qdrant": bool, "redis": bool, "postgres": bool } }

POST /ingest
  Request:  { "source": "gcp_docs" }
  Response: { "status": "started", "job_id": string }

GET /ingest/{job_id}
  Response: { "status": "running|complete|failed", "docs_indexed": int }
```

### Ingestion execution strategy


| Environment | Behavior                                                                                          |
| ----------- | ------------------------------------------------------------------------------------------------- |
| Local       | FastAPI **BackgroundTasks** (or equivalent in-process async) drives ingestion job state           |
| Production  | **Cloud Run Job** performs ingestion work; API triggers job and persists pollable `job_id` status |


---

## 9. Ingestion Pipeline

### GCP Documentation Sources

- Cloud Run documentation (PDF export)
- Vertex AI documentation (PDF export)
- BigQuery documentation (PDF export)
- GKE documentation (PDF export)
- Cloud Storage documentation (PDF export)

Target: 15–20 documents, ~500–800 pages total

### Chunking Strategy

```
1. Parse PDF with LlamaIndex SimpleDirectoryReader
2. Split by section headers (H1, H2 boundaries)
3. Max chunk size: 512 tokens
4. Overlap: 50 tokens between adjacent chunks
5. Metadata per chunk:
   - source_doc: filename
   - section: header text
   - product: inferred GCP product
   - page_number: original PDF page
6. Fallback: fixed-size splitter + overlap when heading structure unusable — log WARN metric
```

### Embedding

- Model: Vertex AI `text-embedding-005` (configurable; avoid retired `text-embedding-004`)
- Batch size: 100 chunks per API call
- Store: Qdrant collection `gcp_docs`

---

## 10. Evaluation Plan

### Golden Dataset (30 cases)

- 10 retrieval queries — factual questions answerable from GCP docs
- 10 code generation queries — practical GCP code tasks
- 10 analytics queries — structured questions about doc metadata

### RAGAS Metrics (RAG Agent)


| Metric            | Target |
| ----------------- | ------ |
| Faithfulness      | > 0.85 |
| Answer relevance  | > 0.80 |
| Context precision | > 0.75 |
| Context recall    | > 0.75 |


### DeepEval Metrics (All Agents)


| Metric                | Target                                                                               |
| --------------------- | ------------------------------------------------------------------------------------ |
| Tool call correctness | > 0.90                                                                               |
| Answer correctness    | > 0.80                                                                               |
| Latency p95           | **Split by path** — see §14 (global **< 5 s** does not apply to E2B code execution). |
| Cost per query        | < $0.05                                                                              |


### Eval workflow

```
1. Run DeepEval suite against golden dataset (scheduled / manual — see CI policy)
2. Identify lowest scoring metric
3. Trace failing cases in Langfuse
4. Tune system prompt of relevant agent
5. Re-run, document delta
6. Repeat until targets met
```

### CI policy


| Trigger          | Gates                                                    |
| ---------------- | -------------------------------------------------------- |
| Pull request     | **Unit / integration tests** (fast suite)                |
| Nightly / manual | **Eval harness** (RAGAS + DeepEval — slower, LLM-costly) |


---

## 11. Observability

### Langfuse Instrumentation

Every LangGraph node emits:

- Span name (agent name + step)
- Input / output tokens
- Latency
- Model used
- LLM call cost (estimated)

**v1 deployment:** Langfuse **hosted project keys** via env / Secret Manager (no Langfuse Cloud Run service in production for this phase).

### Cloud Monitoring Dashboard

- Request rate (qps)
- p50 / p95 / p99 latency
- Error rate by agent
- Token cost per hour
- Qdrant query latency
- Redis hit/miss ratio (session envelope lookups)

### Alerting


| Alert                    | Threshold                                                               |
| ------------------------ | ----------------------------------------------------------------------- |
| API error rate           | > 5% over 5 min                                                         |
| p95 latency              | > 8s *(tune per route/intent if Code Agent + E2B dominates global p95)* |
| Qdrant unavailable       | Any                                                                     |
| Cloud Run instance count | > 10 (cost alert)                                                       |


---

## 12. Infrastructure

### Region & secrets

- **Primary region:** `us-central1` for Vertex AI, Cloud Run services, and BigQuery jobs aligned with stack defaults.
- **Secret Manager:** store **E2B API key** and API-key **pepper** (and Langfuse keys); inject into Cloud Run at deploy time.

### Cloud Run Services (v1)


| Service       | CPU | Memory | Min instances | Max instances                               |
| ------------- | --- | ------ | ------------- | ------------------------------------------- |
| API (FastAPI) | 2   | 4Gi    | 0             | 10                                          |
| Qdrant        | 2   | 4Gi    | 1             | 1                                           |
| *(Langfuse)*  | —   | —      | —             | **Hosted SaaS — not deployed on Run in v1** |


### Cloud Build Pipeline

Source of truth: [infra/cloudbuild.yaml](infra/cloudbuild.yaml) (image push to **Artifact Registry** + `gcloud run deploy` in **us-central1**), [infra/cloudbuild.pr.yaml](infra/cloudbuild.pr.yaml) (PR unit tests). See [infra/README.md](infra/README.md) for Secret Manager names and IAM.

```yaml
# Illustrative shape; use repo file for exact flags/substitutions.
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'infra/Dockerfile', '-t', '$_REGION-docker.pkg.dev/$PROJECT_ID/querymesh/api:$BUILD_ID', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '$_REGION-docker.pkg.dev/$PROJECT_ID/querymesh/api:$BUILD_ID']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'gcloud'
    args: ['run', 'deploy', 'api', '--image', '...', '--region', 'us-central1']
# triggers: push to main → cloudbuild.yaml; PR → cloudbuild.pr.yaml
```

**PR triggers:** Run automated tests on PR (configure Cloud Build or GitHub Actions per repo preference).

---

## 13. Local Development

Authoritative tooling: **Python 3.12**, **uv** + [pyproject.toml](pyproject.toml) (no `requirements.txt`); Docker for Postgres, Redis, and Qdrant ([infra/docker-compose.yml](infra/docker-compose.yml)). See also [AGENTS.md](AGENTS.md) and [spec_phase2.md](spec_phase2.md) developer path.

```bash
# Start local dependencies (repo root)
docker compose -f infra/docker-compose.yml up -d

# Install app dependencies (no pip install -r requirements.txt)
uv sync

# Environment
cp .env.example .env   # GOOGLE_CLOUD_PROJECT, DATABASE_URL, REDIS_URL, API_KEY_PEPPER, …

# Database schema (Alembic does not auto-load .env; pass it explicitly)
uv run --env-file .env alembic upgrade head

# API key (once per user)
PYTHONPATH=. uv run --env-file .env python scripts/mint_api_key.py

# Bootstrap BigQuery synthetic dataset (once per env; ADC required)
PYTHONPATH=. uv run --env-file .env python scripts/bootstrap_bq.py --project YOUR_PROJECT_ID

# Ingestion — CLI path (or use POST /ingest with INGESTION_GCP_DOCS_DIR set)
PYTHONPATH=. uv run --env-file .env python -m ingestion.indexer \
  --source ./corpus/gcp_docs \
  --google-cloud-project YOUR_PROJECT_ID

# API (host)
PYTHONPATH=. uv run --env-file .env uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Tests (PR-equivalent; stub env if .env is incomplete — see .github/workflows/ci.yml)
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/querymesh
export API_KEY_PEPPER=local-dev-pepper
export REDIS_URL=redis://localhost:6379/0
export RATE_LIMIT_STORAGE_URI=memory://
uv run pytest -q

# Evals (optional; install eval group first)
uv sync --group eval
PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --dry-run
RUN_EVAL=1 PYTHONPATH=. uv run --group eval python -m evals.ragas_eval --limit 5
RUN_EVAL=1 uv run --group eval pytest evals/test_deepeval_suite.py -v
```

**Corpus / reindex:** [docs/corpus_runbook.md](docs/corpus_runbook.md).

**Step-by-step (compose, Alembic, mint key, browser demo):** [docs/local_dev.md](docs/local_dev.md).

---

## 14. Success Criteria


| Criteria                                                                                                                                             | Target                                                                |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| All three agents functional                                                                                                                          | ✅                                                                     |
| End-to-end latency p95 (**non–code-execution paths**: RAG, Analytics, orchestrator/routing, synthesizer when no E2B run)                             | **< 5 seconds**                                                       |
| End-to-end latency p95 (**Code Agent invokes E2B** — sandbox spin-up ~~1–2 s cold plus generation + execution; realistic totals often **~~15–20 s**) | **< 25 seconds** *(separate budget — not a failure vs the row above)* |
| RAGAS faithfulness                                                                                                                                   | > 0.85                                                                |
| DeepEval tool call correctness                                                                                                                       | > 0.90                                                                |
| Langfuse traces visible for every query                                                                                                              | ✅                                                                     |
| Cloud Monitoring dashboard live                                                                                                                      | ✅                                                                     |
| CI/CD pipeline deploying on push                                                                                                                     | ✅                                                                     |
| Repo documented with architecture diagram                                                                                                            | ✅                                                                     |


---

## 15. Implementation build order

Use this sequence to unblock dependencies early and keep integrations testable.

1. **Repo scaffold** — Python layout (`agents/`, `graph/`, `api/`, `memory/`, `tools/`), `requirements.txt`, `pyproject.toml` if applicable, `.env.example`, linters/formatters.
2. **Infra primitives (local)** — `docker-compose.yml` for **Qdrant + Redis**; document hosted Langfuse env vars.
3. **Postgres schema & migrations** — `users`, `api_keys`, `user_memory`, LangGraph checkpointer tables; constraints (`CHECK memory_type`), indexes.
4. **Auth middleware** — Bearer parsing → digest → `user_internal_id`; constant-time compare; issue CLI helper or script to mint keys + associate `users` row.
5. **Session layer** — Redis envelope + bind/mint `session_id`; **403** on mismatch; composite `**thread_id`** for LangGraph.
6. **Long-term memory reads** — Top-k loader + **256-token** compaction + ordering rules; wire before orchestrator node.
7. **LangGraph skeleton** — Stateful graph + checkpointer + Redis noop extras; single-path “echo” then orchestrstrator stub.
8. **RAG vertical slice** — Ingestion CLI (`loader`/`chunker`/`indexer`), Qdrant collection, retrieval node, optional rerank flag (**off local**).
9. **Orchestrator** — Structured routing JSON + retry then **RAG fallback**; enforce **fan-out ≤ 3**; temperatures per policy.
10. **Synthesizer** — Render structured RAG JSON; bind `**save_memory`** tool only here.
11. **Analytics vertical slice** — `scripts/bootstrap_bq.py` + README; IAM least privilege; analytics agent + guarded SQL executor.
12. **Code agent + E2B** — Template (**Python**, **no egress**, baked libs); `**code_exec_tool`**; caps (**15s**, **64KiB**, **2** concurrent/replica).
13. **Parallel fan-out & synthesis** — Full multi-agent paths; Langfuse spans end-to-end.
14. `**/query` Hard API** — Rate limit (**60/min**), latency + `**session_id`** envelope, stable **403** JSON errors.
15. **Ingestion API** — Local BackgroundTasks job tracker; prod **Cloud Run Job** trigger + status persistence for `job_id`.
16. **Observability & dashboards** — Langfuse hosted wiring; Cloud Monitoring dashboard + alerts from §11–§12.
17. **Eval harness** — Golden dataset + RAGAS + DeepEval runners; schedule **nightly/manual**; keep **pytest fast** on PR.
18. **Cloud Build & Run deploy** — Dockerfile, `cloudbuild.yaml`, secrets via Secret Manager; **us-central1** deploy of API (+ Qdrant if not managed elsewhere).

Checkpoint criteria between phases: **(a)** auth + session tests green before agents; **(b)** RAG path produces traces before enabling rerank in prod; **(c)** BigQuery bootstrap repeatable before Analytics eval cases; **(d)** E2B template pinned + regression test for sandbox timeouts before exposing execution broadly.