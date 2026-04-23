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

## Production build

```bash
npm run build
npm start
```
