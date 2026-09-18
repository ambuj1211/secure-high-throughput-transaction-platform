from fastapi import FastAPI

app = FastAPI(
    title="Secure High-Throughput Transaction Processing Platform",
    version="0.1.0",
)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
