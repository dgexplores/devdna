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
        assert test_client.get("/health/live").json() == {"status": "ok"}


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
