import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from rq import Queue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.analyses import router as analyses_router
from devdna.config import Settings, get_settings
from devdna.logging import configure_logging
from devdna.web import asset_directory
from devdna.web import router as web_router

ReadinessCheck = Callable[[], Awaitable[dict[str, str]]]
logger = logging.getLogger(__name__)
RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return {current, redis.call("TTL", KEYS[1])}
"""


def add_security_headers(response: Any, path: str) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path == "/" or path.startswith("/reports/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )


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
        app.state.sessions = async_sessionmaker(app.state.database, expire_on_commit=False)
        app.state.redis = Redis.from_url(settings.redis_url)
        app.state.rate_limiter = app.state.redis
        app.state.queue_redis = SyncRedis.from_url(settings.redis_url)
        app.state.queue = Queue("devdna", connection=app.state.queue_redis)
        yield
        app.state.queue_redis.close()
        await app.state.redis.aclose()
        await app.state.database.dispose()

    app = FastAPI(title="DevDNA API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def harden_requests(request: Request, call_next: Callable[..., Awaitable[Any]]) -> Any:
        content_length = request.headers.get("content-length")
        if request.method in {"POST", "PUT", "PATCH"} and content_length is None:
            response = JSONResponse(
                status_code=status.HTTP_411_LENGTH_REQUIRED,
                content={"detail": "Content-Length header is required"},
            )
            add_security_headers(response, request.url.path)
            return response
        if request.method in {"POST", "PUT", "PATCH"}:
            assert content_length is not None
            try:
                request_bytes = int(content_length)
            except ValueError:
                response = JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header"},
                )
                add_security_headers(response, request.url.path)
                return response
            if request_bytes < 0:
                response = JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header"},
                )
                add_security_headers(response, request.url.path)
                return response
            if request_bytes > settings.max_request_bytes:
                response = JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Request body is too large"},
                )
                add_security_headers(response, request.url.path)
                return response

        rate_headers: dict[str, str] = {}
        if request.method == "POST" and request.url.path == "/v1/analyses":
            # ponytail: use the direct peer until deployment has a trusted-proxy allowlist.
            client_host = request.client.host if request.client else "unknown"
            key = f"devdna:rate:analysis:{client_host}"
            try:
                result = await request.app.state.rate_limiter.eval(
                    RATE_LIMIT_SCRIPT,
                    1,
                    key,
                    settings.analysis_rate_window_seconds,
                )
                current, ttl = int(result[0]), max(1, int(result[1]))
            except Exception:
                logger.exception("Analysis rate limiter failed")
                response = JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "Rate limiter unavailable"},
                )
                add_security_headers(response, request.url.path)
                return response

            rate_headers = {
                "X-RateLimit-Limit": str(settings.analysis_rate_limit),
                "X-RateLimit-Remaining": str(max(0, settings.analysis_rate_limit - current)),
            }
            if current > settings.analysis_rate_limit:
                response = JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Analysis request limit exceeded"},
                    headers={**rate_headers, "Retry-After": str(ttl)},
                )
                add_security_headers(response, request.url.path)
                return response

        response = await call_next(request)
        response.headers.update(rate_headers)
        add_security_headers(response, request.url.path)
        return response

    app.include_router(analyses_router)
    assets = asset_directory()
    if not assets.is_dir():
        raise RuntimeError("Web assets are missing")
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    app.include_router(web_router)

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
