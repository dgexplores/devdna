import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from devdna.config import Settings
from devdna.database import Base
from devdna.main import create_app


class FakeQueue:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.jobs.append((args, kwargs))


def create_test_client(database_path: Path, queue: FakeQueue) -> TestClient:
    database_url = f"sqlite+aiosqlite:///{database_path}"

    async def create_schema() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())
    app = create_app(Settings(environment="test", database_url=database_url))
    client = TestClient(app)
    client.__enter__()
    app.state.queue = queue
    return client


def test_create_and_get_analysis(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(tmp_path / "api.db", queue)
    try:
        created = client.post(
            "/v1/analyses",
            json={
                "github_username": "Octocat",
                "target_role": "python_backend_developer",
            },
        )
        duplicate = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
        )
        fetched = client.get(f"/v1/analyses/{created.json()['id']}")
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 202
    assert created.json()["github_username"] == "octocat"
    assert created.json()["status"] == "queued"
    assert duplicate.json()["id"] == created.json()["id"]
    assert fetched.status_code == 200
    assert len(queue.jobs) == 1
    assert queue.jobs[0][1]["retry"].max == 2


def test_rejects_invalid_github_username(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "invalid.db", FakeQueue())
    try:
        response = client.post(
            "/v1/analyses",
            json={
                "github_username": "-invalid--name",
                "target_role": "python_backend_developer",
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 422


def test_marks_analysis_failed_when_queue_is_unavailable(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "queue.db", FakeQueue(fail=True))
    try:
        response = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "Analysis queue unavailable"
