# QueryMesh web UI (Next.js)

Simple TypeScript UI for Google-backed portal sign-in, API key minting, chat (`POST /query`), and eval reports at **`/eval`** (`GET /eval-reports`). **`/eval`** appears in the header only after sign-in. When signed in, the top-right **avatar** (initials from your email) opens a menu with your **name** and **email** (from OAuth-backed claims in the portal JWT) and **Sign out**.

## Run (**Docker — recommended**)

The UI ships as a **production** standalone image (`output: "standalone"`). Run it via Compose from the repo root so `NEXT_PUBLIC_*` is wired at **build time**.

```bash
# From repo root (starts Postgres, Redis, Qdrant, and web on :3000)
docker compose -f infra/docker-compose.yml up -d
# After changing infra/docker-compose.yml web.build.args or web/Dockerfile:
# docker compose -f infra/docker-compose.yml up -d --build web
```

Then open [http://localhost:3000](http://localhost:3000). Run FastAPI on the host (or wherever the browser can reach) on **port 8000** so `NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000` matches (`infra/docker-compose.yml` `web.build.args`).

**Custom API or Langfuse base:** edit **`infra/docker-compose.yml`** under `web.build.args`:

- **`NEXT_PUBLIC_QUERYMESH_URL`** — API base URL the **browser** must reach (never `host.docker.internal` unless it resolves in the user’s browser).
- **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** — Langfuse region for `/eval` trace links (e.g. `https://us.cloud.langfuse.com`). Re-run compose with **`--build`** after changing args.

Standalone image (no Compose):

```bash
docker build -f web/Dockerfile \
  --build-arg NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000 \
  --build-arg NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=https://cloud.langfuse.com \
  -t querymesh-web:local .
docker run --rm -p 3000:3000 querymesh-web:local
```

## Alternative — Node on the host (`npm`)

Use **Node.js 20.x** (matches [`Dockerfile`](Dockerfile)). Only useful for active UI development without rebuilding the Docker image:

```bash
cd web
cp .env.example .env.local
# Set NEXT_PUBLIC_QUERYMESH_URL and NEXT_PUBLIC_LANGFUSE_PUBLIC_URL in .env.local
npm install
npm run dev
```

## Deploy on Vercel (alternate to Cloud Run `web`)

1. Import the repo in [Vercel](https://vercel.com) with **Root Directory** = `web`.
2. Under **Project → Settings → Environment Variables** (Production and Preview as needed), set:
   - **`NEXT_PUBLIC_QUERYMESH_URL`** — public HTTPS URL of the QueryMesh API (Cloud Run `api` service). **Trigger a new deployment** after changing this; the value is baked at build time.
   - **`NEXT_PUBLIC_LANGFUSE_PUBLIC_URL`** — Langfuse UI base for `/eval` trace links (e.g. `https://us.cloud.langfuse.com`).
3. Ensure the API allows your Vercel origin via **CORS** — configure `cors_allow_origins` / `cors_allow_origin_regex` in Terraform and run **`tf-apply`**, or extend `_CORS_ALLOW_ORIGINS` (comma-separated) on the **`tf-apply`** Cloud Build trigger. See [infra/README.md](../infra/README.md).

## Requirements

- FastAPI must expose **`NEXT_PUBLIC_QUERYMESH_URL`** with **`PORTAL_JWT_SECRET`**, Google OAuth env vars (**`GOOGLE_*`**, **`PORTAL_FRONTEND_BASE_URL`** on the API), and **`CORS_ALLOW_ORIGINS`** including `http://localhost:3000` (or `*` locally).

## Docker / production parity

Production Cloud Build uses [`web/Dockerfile`](Dockerfile); local Compose uses the same file. To verify a production bundle locally:

```bash
docker build -f web/Dockerfile \
  --build-arg NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000 \
  --build-arg NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=https://cloud.langfuse.com \
  -t querymesh-web:local .
docker run --rm -p 3000:3000 querymesh-web:local
```
