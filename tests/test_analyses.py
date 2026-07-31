import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.config import Settings
from devdna.database import Base
from devdna.main import create_app
from devdna.models import AnalysisRun
from devdna.reports import generate_report
from devdna.schemas import EvidenceSnapshot


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
    queue: FakeQueue,
    *,
    rate_limit: int = 10,
    max_request_bytes: int = 16_384,
    rate_limiter: FakeRateLimiter | None = None,
    api_keys: str | None = None,
) -> TestClient:
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
            analysis_rate_limit=rate_limit,
            max_request_bytes=max_request_bytes,
            api_keys=SecretStr(api_keys) if api_keys else None,
        )
    )
    client = TestClient(app)
    client.__enter__()
    app.state.queue = queue
    app.state.rate_limiter = rate_limiter or FakeRateLimiter()
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
        pending_report = client.get(f"/v1/analyses/{created.json()['id']}/report")
        pending_readme = client.get(f"/v1/analyses/{created.json()['id']}/readme")
        pending_page = client.get(f"/reports/{created.json()['id']}")
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 202
    assert created.json()["github_username"] == "octocat"
    assert created.json()["status"] == "queued"
    assert duplicate.json()["id"] == created.json()["id"]
    assert fetched.status_code == 200
    assert pending_report.status_code == 409
    assert pending_report.json()["detail"] == "Report is not ready"
    assert pending_readme.status_code == 409
    assert pending_readme.json()["detail"] == "README draft is not ready"
    assert pending_page.status_code == 202
    assert "Reading octocat’s work" in pending_page.text
    assert 'aria-busy="true"' in pending_page.text
    assert len(queue.jobs) == 1
    assert queue.jobs[0][1]["job_timeout"] == 300
    assert queue.jobs[0][1]["retry"].max == 2


def test_web_form_starts_analysis_and_redirects_to_progress(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(tmp_path / "web-form.db", queue)
    try:
        home = client.get("/")
        submitted = client.post(
            "/analyses",
            data={
                "github_username": "Octocat",
                "target_role": "python_backend_developer",
            },
            follow_redirects=False,
        )
        progress = client.get(submitted.headers["location"])
    finally:
        client.__exit__(None, None, None)

    assert home.status_code == 200
    assert '<form class="analysis-form" method="post" action="/analyses">' in home.text
    assert submitted.status_code == 303
    assert submitted.headers["location"].startswith("/reports/")
    assert submitted.headers["X-RateLimit-Remaining"] == "9"
    assert progress.status_code == 202
    assert "Reading octocat’s work" in progress.text
    assert len(queue.jobs) == 1


def test_duplicate_request_recovers_missing_queue_job(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(tmp_path / "recover-queue.db", queue)
    payload = {
        "github_username": "octocat",
        "target_role": "python_backend_developer",
    }
    try:
        created = client.post("/v1/analyses", json=payload)
        queue.jobs.clear()
        recovered = client.post("/v1/analyses", json=payload)
    finally:
        client.__exit__(None, None, None)

    assert recovered.status_code == 202
    assert recovered.json()["id"] == created.json()["id"]
    assert recovered.json()["status"] == "queued"
    assert len(queue.jobs) == 1
    assert queue.jobs[0][1]["job_id"] == created.json()["id"]


def test_web_form_returns_inline_validation_error(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "web-form-invalid.db", FakeQueue())
    try:
        response = client.post(
            "/analyses",
            data={
                "github_username": "-invalid--name",
                "target_role": "python_backend_developer",
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 422
    assert 'class="form-error"' in response.text
    assert "Enter a valid GitHub username" in response.text
    assert 'aria-describedby="analysis-error"' in response.text


def test_web_form_requires_configured_access_key(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(
        tmp_path / "web-form-auth.db",
        queue,
        api_keys="developer=correct-horse-battery-staple",
    )
    payload = {
        "github_username": "octocat",
        "target_role": "python_backend_developer",
    }
    try:
        home = client.get("/")
        missing = client.post("/analyses", data=payload)
        allowed = client.post(
            "/analyses",
            data={**payload, "access_key": "developer.correct-horse-battery-staple"},
            follow_redirects=False,
        )
    finally:
        client.__exit__(None, None, None)

    assert 'type="password"' in home.text
    assert missing.status_code == 401
    assert "Valid bearer API key required" in missing.text
    assert allowed.status_code == 303
    assert len(queue.jobs) == 1


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


def test_rejects_oversized_analysis_request(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "oversized.db",
        FakeQueue(),
        max_request_bytes=1024,
    )
    try:
        response = client.post(
            "/v1/analyses",
            content=b"x" * 1025,
            headers={"Content-Type": "application/json"},
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large"


def test_requires_length_for_analysis_request(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "length-required.db", FakeQueue())
    try:
        response = client.post(
            "/v1/analyses",
            content=iter([b"{}"]),
            headers={"Content-Type": "application/json"},
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 411
    assert response.json()["detail"] == "Content-Length header is required"


def test_rate_limits_analysis_creation(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "rate-limit.db", FakeQueue(), rate_limit=1)
    try:
        allowed = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
        )
        blocked = client.post(
            "/v1/analyses",
            json={
                "github_username": "another-user",
                "target_role": "python_backend_developer",
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert allowed.status_code == 202
    assert allowed.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "1"
    assert int(blocked.headers["Retry-After"]) > 0


def test_requires_configured_api_key_and_rate_limits_each_client(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "authenticated-rate-limit.db",
        FakeQueue(),
        rate_limit=1,
        api_keys=("developer=correct-horse-battery-staple,recruiter=another-long-secret-value"),
    )
    payload = {
        "github_username": "octocat",
        "target_role": "python_backend_developer",
    }
    try:
        missing = client.post("/v1/analyses", json=payload)
        developer = client.post(
            "/v1/analyses",
            json=payload,
            headers={
                "Authorization": "Bearer developer.correct-horse-battery-staple",
            },
        )
        developer_blocked = client.post(
            "/v1/analyses",
            json=payload,
            headers={
                "Authorization": "Bearer developer.correct-horse-battery-staple",
            },
        )
        recruiter = client.post(
            "/v1/analyses",
            json=payload,
            headers={"Authorization": "Bearer recruiter.another-long-secret-value"},
        )
    finally:
        client.__exit__(None, None, None)

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert missing.headers["X-RateLimit-Remaining"] == "0"
    assert developer.status_code == 202
    assert developer_blocked.status_code == 429
    assert recruiter.status_code == 202


def test_fails_closed_when_rate_limiter_is_unavailable(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "rate-limit-down.db",
        FakeQueue(),
        rate_limiter=FakeRateLimiter(fail=True),
    )
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
    assert response.json()["detail"] == "Rate limiter unavailable"


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


def test_get_analysis_exposes_partial_result(tmp_path: Path) -> None:
    database_path = tmp_path / "partial-api.db"
    client = create_test_client(database_path, FakeQueue())
    try:
        created = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
        )
        analysis_id = created.json()["id"]

        async def mark_partial() -> None:
            engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                analysis = await session.get(AnalysisRun, analysis_id)
                assert analysis is not None
                analysis.status = "partial"
                analysis.profile_snapshot = {"profile": {"login": "octocat"}}
                analysis.evidence_snapshot = {
                    "schema_version": "1",
                    "analyzer_version": "python-backend-evidence-v1",
                    "target_role": "python_backend_developer",
                    "rubric_version": "python_backend_developer:v1",
                    "repositories_analyzed": 0,
                    "items": [],
                }
                analysis.report_snapshot = generate_report(
                    EvidenceSnapshot.model_validate(analysis.evidence_snapshot),
                    "partial",
                    "Repository collection failed",
                ).model_dump(mode="json")
                analysis.error_message = "Repository collection failed"
                await session.commit()
            await engine.dispose()

        asyncio.run(mark_partial())
        response = client.get(f"/v1/analyses/{analysis_id}")
        report_response = client.get(f"/v1/analyses/{analysis_id}/report")
        readme_response = client.get(f"/v1/analyses/{analysis_id}/readme")
        report_page = client.get(f"/reports/{analysis_id}")
        readme_page = client.get(f"/reports/{analysis_id}/readme")
        readme_download = client.get(f"/reports/{analysis_id}/readme.md")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["profile_snapshot"]["profile"]["login"] == "octocat"
    assert response.json()["evidence_snapshot"]["analyzer_version"] == (
        "python-backend-evidence-v1"
    )
    assert response.json()["error_message"] == "Repository collection failed"
    assert report_response.status_code == 200
    assert report_response.json()["collection_status"] == "partial"
    assert readme_response.status_code == 200
    assert readme_response.json()["github_username"] == "octocat"
    assert report_page.status_code == 200
    assert "The evidence spine" in report_page.text
    assert "Partial inspection" in report_page.text
    assert readme_page.status_code == 200
    assert "A stronger profile" in readme_page.text
    assert readme_download.status_code == 200
    assert readme_download.headers["content-type"].startswith("text/markdown")
    assert 'filename="README.md"' in readme_download.headers["content-disposition"]
