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

    def fetch_job(self, job_id: str) -> object | None:
        return next(
            (object() for _, options in self.jobs if options.get("job_id") == job_id),
            None,
        )

    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("queue unavailable")
        self.jobs.append((args, kwargs))


class FakeRateLimiter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = {}

    async def eval(self, _: str, __: int, key: str, window: int) -> list[int]:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], window]


def create_test_client(
    database_path: Path,
    queue: FakeQueue | None = None,
    *,
    rate_limiter: FakeRateLimiter | None = None,
    **setting_overrides: Any,
) -> TestClient:
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
    app.state.queue = queue or FakeQueue()
    app.state.rate_limiter = rate_limiter or FakeRateLimiter()
    return client
