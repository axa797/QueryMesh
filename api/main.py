from fastapi import FastAPI

app = FastAPI(title="querymesh", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness + dependency status. Service checks stay false until wired (spec §8 API)."""
    return {
        "status": "ok",
        "services": {
            "qdrant": False,
            "redis": False,
            "postgres": False,
        },
    }
