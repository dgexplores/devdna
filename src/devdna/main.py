import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from devdna.config import Settings, get_settings
from devdna.logging import configure_logging

ReadinessCheck = Callable[[], Awaitable[dict[str, str]]]
logger = logging.getLogger(__name__)


async def check_dependencies(app: FastAPI) -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        async with app.state.database.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "up"
    except Exception:
        logger.exception("Database readiness check failed")
        checks["database"] = "down"

    try:
        checks["redis"] = "up" if await app.state.redis.ping() else "down"
    except Exception:
        logger.exception("Redis readiness check failed")
        checks["redis"] = "down"
    return checks


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.redis = Redis.from_url(settings.redis_url)
        yield
        await app.state.redis.aclose()
        await app.state.database.dispose()

    app = FastAPI(title="DevDNA API", version="0.1.0", lifespan=lifespan)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness(request: Request) -> Any:
        checks = await (readiness_check or (lambda: check_dependencies(request.app)))()
        required = {"database", "redis"}
        ready = required.issubset(checks) and all(value == "up" for value in checks.values())
        code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=code,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    return app


app = create_app()
