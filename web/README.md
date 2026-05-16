# QueryMesh web UI (Next.js)

Simple TypeScript UI for portal signup/login, API key minting, chat (`POST /query`), and eval reports at **`/eval`** (`GET /eval-reports`).

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

Only useful for active UI development without rebuilding the Docker image:

```bash
cd web
cp .env.example .env.local
# Set NEXT_PUBLIC_QUERYMESH_URL and NEXT_PUBLIC_LANGFUSE_PUBLIC_URL in .env.local
npm install
npm run dev
```

## Requirements

- FastAPI must expose **`NEXT_PUBLIC_QUERYMESH_URL`** with `PORTAL_JWT_SECRET`, `CORS_ALLOW_ORIGINS` including `http://localhost:3000` (or `*` locally).

## Docker / production parity

Production Cloud Build uses [`web/Dockerfile`](Dockerfile); local Compose uses the same file. To verify a production bundle locally:

```bash
docker build -f web/Dockerfile \
  --build-arg NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000 \
  --build-arg NEXT_PUBLIC_LANGFUSE_PUBLIC_URL=https://cloud.langfuse.com \
  -t querymesh-web:local .
docker run --rm -p 3000:3000 querymesh-web:local
```
