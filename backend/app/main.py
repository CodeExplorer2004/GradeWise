import re
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, charts, chat, dashboard, imports, insights, reports, risks, tasks
from app.core.config import get_settings
from app.core.database import SessionLocal, engine, readonly_engine
from app.core.logging import configure_logging
from app.core.seed import seed_demo_data
from app.services.conversation_memory import conversation_memory
from app.services.health import readiness_status
from app.services.login_rate_limit import login_rate_limiter
from app.services.security_headers import apply_security_headers

settings = get_settings()
configure_logging(settings.environment)
logger = structlog.get_logger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application_starting", environment=settings.environment)
    if settings.seed_fake_data:
        async with SessionLocal() as session:
            await seed_demo_data(session)
        logger.info("demo_data_seeded")
    try:
        yield
    finally:
        await conversation_memory.redis.aclose()
        await login_rate_limiter.redis.aclose()
        await engine.dispose()
        await readonly_engine.dispose()
        logger.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(response)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = (
        supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else str(uuid4())
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        raise
    else:
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return response
    finally:
        structlog.contextvars.clear_contextvars()


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
app.include_router(insights.router, prefix=settings.api_prefix)
app.include_router(reports.router, prefix=settings.api_prefix)
app.include_router(risks.router, prefix=settings.api_prefix)
app.include_router(imports.router, prefix=settings.api_prefix)
app.include_router(charts.router, prefix=settings.api_prefix)
app.include_router(tasks.router, prefix=settings.api_prefix)


@app.get("/health")
async def health() -> JSONResponse:
    return await readiness()


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness() -> JSONResponse:
    result = await readiness_status()
    return JSONResponse(
        status_code=200 if result["status"] == "ok" else 503,
        content=result,
    )
