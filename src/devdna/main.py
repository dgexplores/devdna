import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from rq import Queue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from devdna.analyses import router as analyses_router
from devdna.config import Settings, get_settings
from devdna.logging import configure_logging
from devdna.observability import RequestMetrics, request_id
from devdna.recruiter import router as recruiter_router
from devdna.security import parse_api_keys
from devdna.web import asset_directory
from devdna.web import router as web_router

ReadinessCheck = Callable[[], Awaitable[dict[str, str]]]
logger = logging.getLogger(__name__)


def add_security_headers(response: Response, path: str) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if path == "/" or path.startswith("/reports/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net; worker-src 'self' blob:; "
            "connect-src 'self' "
            "https://*.clerk.accounts.dev https://clerk.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "frame-src https://*.clerk.accounts.dev https://challenges.cloudflare.com; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
    api_credentials = parse_api_keys(settings.api_keys)
    web_session_secret = (
        settings.web_session_secret.get_secret_value().strip()
        if settings.web_session_secret
        else ""
    )
    if settings.environment in {"staging", "production"} and not api_credentials:
        raise ValueError("DEVDNA_API_KEYS is required for the API in staging and production")
    if settings.environment in {"staging", "production"} and not web_session_secret:
        raise ValueError(
            "DEVDNA_WEB_SESSION_SECRET is required for the web app in staging and production"
        )

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
    app.state.metrics = RequestMetrics()
    app.state.settings = settings
    app.state.api_credentials = api_credentials
    app.state.web_session_secret = (
        web_session_secret or "devdna-local-session-secret-not-for-production"
    )

    @app.middleware("http")
    async def harden_requests(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
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
            if request.url.path in {"/v1/recruiter/batches", "/recruiter/batches"}:
                request_limit = settings.recruiter_upload_max_bytes
            elif request.url.path.endswith("/cv-alignment") or request.url.path.endswith(
                "/cv-align"
            ):
                # Multipart framing adds a small amount beyond the file itself.
                # The endpoint still enforces the exact file-size limit.
                request_limit = settings.cv_upload_max_bytes + 65_536
            else:
                request_limit = settings.max_request_bytes
            if request_bytes > request_limit:
                response = JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Request body is too large"},
                )
                add_security_headers(response, request.url.path)
                return response

        downstream_response = await call_next(request)
        add_security_headers(downstream_response, request.url.path)
        return downstream_response

    @app.middleware("http")
    async def observe_requests(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        current_request_id = request_id(request.headers.get("x-request-id"))
        request.state.request_id = current_request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started
            route = getattr(request.scope.get("route"), "path", "unmatched")
            app.state.metrics.observe(request.method, route, 500, duration)
            logger.exception(
                "Unhandled request error",
                extra={
                    "request_id": current_request_id,
                    "method": request.method,
                    "route": route,
                    "status_code": 500,
                    "duration_ms": round(duration * 1000, 3),
                    "client_id": getattr(request.state, "api_client_id", None),
                },
            )
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error", "request_id": current_request_id},
            )
            response.headers["X-Request-ID"] = current_request_id
            add_security_headers(response, request.url.path)
            return response

        duration = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        app.state.metrics.observe(request.method, route, response.status_code, duration)
        response.headers["X-Request-ID"] = current_request_id
        request_logger = logger.debug if route == "/health/live" else logger.info
        request_logger(
            "HTTP request completed",
            extra={
                "request_id": current_request_id,
                "method": request.method,
                "route": route,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 3),
                "client_id": getattr(request.state, "api_client_id", None),
            },
        )
        return response

    app.include_router(analyses_router)
    app.include_router(recruiter_router)
    assets = asset_directory()
    if not assets.is_dir():
        raise RuntimeError("Web assets are missing")
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
    app.include_router(web_router)

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness(request: Request) -> JSONResponse:
        checks = await (readiness_check or (lambda: check_dependencies(request.app)))()
        required = {"database", "redis"}
        ready = required.issubset(checks) and all(value == "up" for value in checks.values())
        code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=code,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            request.app.state.metrics.render(),
            media_type="text/plain; version=0.0.4",
        )

    return app


app = create_app()
