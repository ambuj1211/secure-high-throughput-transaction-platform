import logging
import time

from fastapi import FastAPI, Request

from app.api.routes.auth import router as auth_router
from app.api.routes.transactions import router as transactions_router

logger = logging.getLogger(__name__)

_PERF_SAMPLE_EVERY = 50
_request_counter = 0

app = FastAPI(
    title="Secure High-Throughput Transaction Processing Platform",
)


@app.middleware("http")
async def performance_middleware(request: Request, call_next):
    global _request_counter

    _request_counter += 1
    perf_sample = _request_counter % _PERF_SAMPLE_EVERY == 0

    start = time.perf_counter()

    response = await call_next(request)

    total_ms = (time.perf_counter() - start) * 1000

    if perf_sample and request.url.path == "/api/v1/transactions":
        logger.warning(
            "REQUEST_PERF total=%.2fms status=%s",
            total_ms,
            response.status_code,
        )

    return response


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(transactions_router)