# QueryMesh web UI (Next.js)

Simple TypeScript UI for portal signup/login, API key minting, and chat against `POST /query`.

## Run

```bash
cd web
cp .env.example .env.local
# edit .env.local if the API is not on http://127.0.0.1:8000
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Requirements

- FastAPI must expose **`NEXT_PUBLIC_QUERYMESH_URL`** with:
  - `PORTAL_JWT_SECRET` set (for `/account/register` and `/account/login`)
  - `CORS_ALLOW_ORIGINS` including your web origin (e.g. `http://localhost:3000`, or `*` for local-only)

## Docker

The UI is a normal Next.js **production** image (`output: "standalone"`).

From the **repository root**:

```bash
docker build -f web/Dockerfile \
  --build-arg NEXT_PUBLIC_QUERYMESH_URL=http://127.0.0.1:8000 \
  -t querymesh-web:local .
docker run --rm -p 3000:3000 querymesh-web:local
```

`NEXT_PUBLIC_*` is fixed at **build** time. It must be a URL the **browser** can call (not `host.docker.internal` unless your users’ browsers resolve that). With the API on the host at port **8000**, use `http://127.0.0.1:8000`.

With local backing services:

```bash
docker compose -f infra/docker-compose.yml up -d --build web
```

That publishes **http://localhost:3000**. Run the FastAPI process on the host (or elsewhere) so `:8000` matches the baked URL.

## Production build (Node)

```bash
npm run build
npm start
```
