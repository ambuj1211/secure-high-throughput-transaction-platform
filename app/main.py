from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.transactions import router as transactions_router

app = FastAPI(
    title="Secure High-Throughput Transaction Processing Platform",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(transactions_router)
