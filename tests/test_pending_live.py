import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.config import Settings
from devdna.database import Base
from devdna.main import create_app
from devdna.models import AnalysisRun
from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fetch_job(self, job_id: str) -> object | None:
        return next(
            (object() for _, options in self.jobs if options.get("job_id") == job_id),
            None,
        )

    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((args, kwargs))


class FakeRateLimiter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, _: str, __: int, key: str, window: int) -> list[int]:
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], window]


def create_test_client(database_path: Path) -> TestClient:
    database_url = f"sqlite+aiosqlite:///{database_path}"

    async def create_schema() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())
    app = create_app(
        Settings(
            environment="test",
            database_url=database_url,
        )
    )
    client = TestClient(app)
    client.__enter__()
    app.state.queue = FakeQueue()
    app.state.rate_limiter = FakeRateLimiter()
    return client


def _evidence() -> EvidenceSnapshot:
    return EvidenceSnapshot(
        schema_version="1",
        analyzer_version="test",
        target_role="python_backend_developer",
        rubric_version="python_backend_developer:v1",
        repositories_analyzed=1,
        items=[
            EvidenceItem(
                key="python.project",
                category="language",
                claim="Python project files are present.",
                repository="octocat/backend",
                sources=[
                    EvidenceSource(
                        repository="octocat/backend",
                        path="pyproject.toml",
                        url="https://github.com/octocat/backend/blob/main/pyproject.toml",
                    )
                ],
            )
        ],
    )


def _save_completed_snapshots(database_path: Path, analysis_id: str) -> None:
    evidence = _evidence()

    async def update() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            analysis = await session.get(AnalysisRun, analysis_id)
            assert analysis is not None
            report = generate_report(evidence, "completed")
            analysis.status = "completed"
            analysis.evidence_snapshot = evidence.model_dump(mode="json")
            analysis.report_snapshot = report.model_dump(mode="json")
            await session.commit()
        await engine.dispose()

    asyncio.run(update())


def test_pending_page_uses_live_poller(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "api.db")
    try:
        created = client.post(
            "/v1/analyses",
            json={"github_username": "octocat", "target_role": "python_backend_developer"},
        )
        analysis_id = created.json()["id"]
        page = client.get(f"/reports/{analysis_id}")
        app_js = client.get("/assets/app.js")
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 202
    assert page.status_code == 202
    assert 'data-poll-url="/v1/analyses/' in page.text
    assert f'data-report-url="/reports/{analysis_id}"' in page.text
    assert 'data-initial-status="queued"' in page.text
    assert 'aria-busy="true"' in page.text
    assert "Reading octocat’s work" in page.text
    assert "http-equiv" not in page.text
    assert "/assets/app.js?v=" in page.text
    assert 'role="status"' in page.text

    assert app_js.status_code == 200
    assert app_js.headers["content-type"].startswith(("application/javascript", "text/javascript"))
    assert "IntersectionObserver" in app_js.text
    assert "prefers-reduced-motion" in app_js.text
    assert "data-poll-url" in app_js.text


def test_completed_report_has_no_poller(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    client = create_test_client(database_path)
    try:
        created = client.post(
            "/v1/analyses",
            json={"github_username": "octocat", "target_role": "python_backend_developer"},
        )
        analysis_id = created.json()["id"]
    finally:
        client.__exit__(None, None, None)

    _save_completed_snapshots(database_path, analysis_id)
    client = create_test_client(database_path)
    try:
        page = client.get(f"/reports/{analysis_id}")
    finally:
        client.__exit__(None, None, None)

    assert page.status_code == 200
    assert "data-poll-url" not in page.text
    assert '<script src="/assets/app.js' in page.text


def test_recruiter_batch_pending_page_polls_instead_of_meta_refresh(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "api.db")
    try:
        page = client.get("/recruiter")
    finally:
        client.__exit__(None, None, None)

    assert page.status_code == 200
    assert "http-equiv" not in page.text
