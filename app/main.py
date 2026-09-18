from fastapi import FastAPI

from app.api.routes.transactions import router as transaction_router

app = FastAPI(
    title="Secure High-Throughput Transaction Processing Platform",
    version="0.1.0",
)

app.include_router(transaction_router)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
