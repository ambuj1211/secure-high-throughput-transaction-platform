import logging
import time

from fastapi import FastAPI, Request
from prometheus_client import make_asgi_app

from app.api.routes.account import router as account_router
from app.api.routes.auth import router as auth_router
from app.api.routes.manager import router as manager_router
from app.api.routes.transactions import router as transactions_router
from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY

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

    total_seconds = time.perf_counter() - start
    total_ms = total_seconds * 1000

    path = request.url.path

    if path != "/metrics":
        REQUEST_COUNT.labels(
            method=request.method,
            path=path,
            status=str(response.status_code),
        ).inc()

        REQUEST_LATENCY.labels(
            method=request.method,
            path=path,
        ).observe(total_seconds)

    if perf_sample and path == "/api/v1/transactions":
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
app.include_router(account_router)
app.include_router(manager_router)
app.include_router(transactions_router)

# Prometheus-compatible metrics endpoint.
app.mount("/metrics", make_asgi_app())
