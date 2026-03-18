from fastapi import FastAPI
from memory.database import database_url, ping_postgres

app = FastAPI(title="querymesh", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    """Liveness + dependency status (spec §8 API)."""
    db_url = database_url()
    pg_ok = await ping_postgres(db_url) if db_url else False
    return {
        "status": "ok",
        "services": {
            "qdrant": False,
            "redis": False,
            "postgres": pg_ok,
        },
    }
