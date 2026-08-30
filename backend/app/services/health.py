import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import text

from app.core.database import engine
from app.services.conversation_memory import conversation_memory

logger = structlog.get_logger(__name__)
HEALTH_TIMEOUT_SECONDS = 2


async def _check_database() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis() -> None:
    await conversation_memory.redis.ping()


async def _bounded_check(
    name: str, check: Callable[[], Awaitable[None]]
) -> tuple[str, str]:
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT_SECONDS):
            await check()
    except Exception as exc:
        logger.warning(
            "dependency_unhealthy",
            dependency=name,
            error_type=type(exc).__name__,
        )
        return name, "unavailable"
    return name, "ok"


async def readiness_status() -> dict[str, object]:
    results = await asyncio.gather(
        _bounded_check("database", _check_database),
        _bounded_check("redis", _check_redis),
    )
    checks = dict(results)
    ready = all(value == "ok" for value in checks.values())
    return {"status": "ok" if ready else "degraded", "checks": checks}
