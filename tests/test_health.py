from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from devdna.main import create_app


@asynccontextmanager
async def no_services(_: FastAPI) -> AsyncIterator[None]:
    yield


def client(checks: dict[str, str]) -> TestClient:
    async def readiness() -> dict[str, str]:
        return checks

    app = create_app(readiness_check=readiness)
    app.router.lifespan_context = no_services
    return TestClient(app)


def test_liveness() -> None:
    with client({}) as test_client:
        response = test_client.get("/health/live")

    assert response.json() == {"status": "ok"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_readiness_reports_dependencies() -> None:
    with client({"database": "up", "redis": "up"}) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_fails_when_dependency_is_down() -> None:
    with client({"database": "up", "redis": "down"}) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "up", "redis": "down"},
    }


def test_readiness_fails_when_checks_are_missing() -> None:
    with client({}) as test_client:
        assert test_client.get("/health/ready").status_code == 503


def test_request_id_and_metrics_are_exposed() -> None:
    with client({}) as test_client:
        response = test_client.get("/health/live", headers={"X-Request-ID": "trace-123"})
        metrics = test_client.get("/metrics")

    assert response.headers["X-Request-ID"] == "trace-123"
    assert metrics.status_code == 200
    assert 'route="/health/live",status="200"} 1' in metrics.text


def test_unhandled_errors_return_traceable_response_and_metric() -> None:
    async def readiness() -> dict[str, str]:
        return {}

    app = create_app(readiness_check=readiness)
    app.router.lifespan_context = no_services

    @app.get("/test-error")
    async def fail() -> None:
        raise RuntimeError("unexpected")

    with TestClient(app) as test_client:
        response = test_client.get("/test-error", headers={"X-Request-ID": "error-trace"})
        metrics = test_client.get("/metrics")

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "error-trace"
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": "error-trace",
    }
    assert 'route="/test-error",status="500"} 1' in metrics.text
