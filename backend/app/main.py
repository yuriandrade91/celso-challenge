import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.database import get_session_factory, initialize_database
from app.api.routes import router
from app.api.errors import install_error_handlers
from app.auth.router import router as auth_router
from app.metrics import RUNTIME_METRICS
from app.observability import configure_logging, log_event, request_id_var
from app.routers.dispatcher import router as dispatcher_router
from app.routers.notifications import router as notifications_router
from app.routers.reviews import router as reviews_router
from app.routers.students import router as students_router
from app.routers.terms import router as terms_router
from app.services.demo_metrics import seed_demo_runtime_metrics, sync_demo_executions

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    initialize_database()
    with get_session_factory()() as db:
        sync_demo_executions(db)
    seed_demo_runtime_metrics()
    yield


app = FastAPI(title="Grade Report Dispatcher", lifespan=lifespan)
install_error_handlers(app)


@app.middleware("http")
async def correlate_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming_id = request.headers.get("x-request-id", "")
    request_id = (
        incoming_id
        if _REQUEST_ID_PATTERN.fullmatch(incoming_id)
        else uuid.uuid4().hex
    )
    token = request_id_var.set(request_id)
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        RUNTIME_METRICS.record_http(status_code, duration_ms)
        log_event(
            logger,
            "http.request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            duration_ms=duration_ms,
        )
        request_id_var.reset(token)


# O painel Next.js chama a API pelo próprio servidor (/api/backend); o CORS
# só é necessário para clientes de browser listados explicitamente.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.include_router(router)
app.include_router(auth_router)
app.include_router(dispatcher_router)
app.include_router(students_router)
app.include_router(reviews_router)
app.include_router(terms_router)
app.include_router(notifications_router)
