import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.config import Settings
from devdna.database import Base
from devdna.main import create_app
from devdna.models import AnalysisRun
from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource
from devdna.web_sessions import SESSION_COOKIE, create_web_session

TEST_WEB_SESSION_SECRET = "devdna-local-session-secret-not-for-production"


def web_session_cookie(client_id: str = "clerk_testuser") -> dict[str, str]:
    return {SESSION_COOKIE: create_web_session(client_id, TEST_WEB_SESSION_SECRET, 3600)}


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
    recruiter_upload_max_bytes: int = 1_048_576,
    recruiter_batch_max_candidates: int = 50,
    recruiter_batch_rate_limit: int = 3,
    cv_upload_max_bytes: int = 2_097_152,
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
            recruiter_upload_max_bytes=recruiter_upload_max_bytes,
            recruiter_batch_max_candidates=recruiter_batch_max_candidates,
            recruiter_batch_rate_limit=recruiter_batch_rate_limit,
            cv_upload_max_bytes=cv_upload_max_bytes,
            api_keys=SecretStr(api_keys) if api_keys else None,
        )
    )
    client = TestClient(app)
    client.__enter__()
    app.state.queue = queue
    app.state.rate_limiter = rate_limiter or FakeRateLimiter()
    return client


def create_docx(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def save_completed_snapshots(
    database_path: Path,
    analysis_id: str,
    evidence: EvidenceSnapshot,
) -> None:
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


def cv_evidence() -> EvidenceSnapshot:
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


def test_cv_alignment_is_owner_scoped_and_does_not_promote_cv_only_claims(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "cv-owner.db"
    client = create_test_client(
        database_path,
        FakeQueue(),
        api_keys=("developer=correct-horse-battery-staple,recruiter=another-long-secret-value"),
    )
    developer_headers = {"Authorization": "Bearer developer.correct-horse-battery-staple"}
    recruiter_headers = {"Authorization": "Bearer recruiter.another-long-secret-value"}
    try:
        created = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
            headers=developer_headers,
        )
        analysis_id = created.json()["id"]
        save_completed_snapshots(database_path, analysis_id, cv_evidence())
        cv_file = ("resume.docx", create_docx("Python FastAPI private-marker"))
        aligned = client.post(
            f"/v1/analyses/{analysis_id}/cv-alignment",
            headers=developer_headers,
            files={"file": cv_file},
        )
        hidden = client.post(
            f"/v1/analyses/{analysis_id}/cv-alignment",
            headers=recruiter_headers,
            files={"file": cv_file},
        )
    finally:
        client.__exit__(None, None, None)

    assert aligned.status_code == 200
    skills = {item["skill"]: item for item in aligned.json()["skills"]}
    assert skills["Python"]["status"] == "verified"
    assert skills["FastAPI"]["status"] == "self_reported_unverified"
    assert aligned.json()["suggested_summary"] == "Public GitHub work verifies Python."
    assert hidden.status_code == 404


def test_readme_studio_offers_private_cv_alignment_workflow(tmp_path: Path) -> None:
    database_path = tmp_path / "cv-web.db"
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
        save_completed_snapshots(database_path, analysis_id, cv_evidence())
        studio = client.get(f"/reports/{analysis_id}/readme")
        result = client.post(
            f"/reports/{analysis_id}/cv-align",
            files={"file": ("resume.docx", create_docx("Python Docker"))},
        )
    finally:
        client.__exit__(None, None, None)

    assert studio.status_code == 200
    assert 'enctype="multipart/form-data"' in studio.text
    assert "Your file is processed in memory and is not saved." in studio.text
    assert result.status_code == 200
    assert "Verified in GitHub" in result.text
    assert "CV only — not verified" in result.text


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
        pending_learning = client.get(f"/v1/analyses/{created.json()['id']}/learning")
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
    assert pending_learning.status_code == 409
    assert pending_learning.json()["detail"] == "Learning plan is not ready"
    assert pending_page.status_code == 202
    assert "Reading octocat’s work" in pending_page.text
    assert 'aria-busy="true"' in pending_page.text
    assert len(queue.jobs) == 1
    assert queue.jobs[0][1]["job_timeout"] == 300
    assert queue.jobs[0][1]["retry"].max == 2


def test_cross_origin_mutation_is_rejected(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "cross-origin.db", FakeQueue())
    try:
        response = client.post(
            "/analyses",
            data={"github_username": "octocat"},
            headers={"Origin": "https://evil.example"},
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 403


def test_web_form_starts_analysis_and_redirects_to_progress(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(tmp_path / "web-form.db", queue)
    try:
        home = client.get("/")
        dashboard = client.get("/app")
        client.cookies.set(SESSION_COOKIE, web_session_cookie()[SESSION_COOKIE])
        submitted = client.post(
            "/app/analyze",
            data={
                "github_username": "Octocat",
                "action": "profile",
            },
            follow_redirects=False,
        )
        progress = client.get(submitted.headers["location"])
    finally:
        client.__exit__(None, None, None)

    assert home.status_code == 200
    assert "Turn your GitHub into a hiring signal" in home.text
    assert '<form class="analysis-form" method="post" action="/app/analyze">' in dashboard.text
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


def test_analysis_history_lists_only_authenticated_owner_requests(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "history.db",
        FakeQueue(),
        api_keys=("developer=correct-horse-battery-staple,recruiter=another-long-secret-value"),
    )
    developer_headers = {"Authorization": "Bearer developer.correct-horse-battery-staple"}
    recruiter_headers = {"Authorization": "Bearer recruiter.another-long-secret-value"}
    try:
        created = client.post(
            "/v1/analyses",
            json={
                "github_username": "octocat",
                "target_role": "python_backend_developer",
            },
            headers=developer_headers,
        )
        developer_history = client.get("/v1/analyses", headers=developer_headers)
        recruiter_history = client.get("/v1/analyses", headers=recruiter_headers)
        missing_auth = client.get("/v1/analyses")
    finally:
        client.__exit__(None, None, None)

    assert developer_history.status_code == 200
    assert [item["id"] for item in developer_history.json()] == [created.json()["id"]]
    assert recruiter_history.status_code == 200
    assert recruiter_history.json() == []
    assert missing_auth.status_code == 401


def test_recruiter_batch_is_bounded_and_owner_scoped(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(
        tmp_path / "recruiter-batch.db",
        queue,
        api_keys=("developer=correct-horse-battery-staple,recruiter=another-long-secret-value"),
    )
    developer_headers = {"Authorization": "Bearer developer.correct-horse-battery-staple"}
    recruiter_headers = {"Authorization": "Bearer recruiter.another-long-secret-value"}
    try:
        created = client.post(
            "/v1/recruiter/batches",
            headers=developer_headers,
            data={"target_role": "python_backend_developer"},
            files={
                "file": (
                    "candidates.csv",
                    b"github_username\noctocat\nhubot\n",
                    "text/csv",
                )
            },
        )
        batch_id = created.json()["id"]
        owner_view = client.get(f"/v1/recruiter/batches/{batch_id}", headers=developer_headers)
        other_owner_view = client.get(
            f"/v1/recruiter/batches/{batch_id}", headers=recruiter_headers
        )
    finally:
        client.__exit__(None, None, None)

    assert created.status_code == 202
    assert [item["github_username"] for item in created.json()["candidates"]] == [
        "octocat",
        "hubot",
    ]
    assert all(item["rank"] is None for item in created.json()["candidates"])
    assert owner_view.status_code == 200
    assert other_owner_view.status_code == 404
    assert len(queue.jobs) == 2


def test_recruiter_upload_rejects_invalid_and_large_files(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "recruiter-invalid.db",
        FakeQueue(),
        recruiter_upload_max_bytes=1024,
    )
    try:
        invalid = client.post(
            "/v1/recruiter/batches",
            files={"file": ("candidates.txt", b"octocat", "text/plain")},
        )
        oversized = client.post(
            "/v1/recruiter/batches",
            files={"file": ("candidates.csv", b"x" * 1100, "text/csv")},
        )
    finally:
        client.__exit__(None, None, None)

    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Upload a .csv or .docx file"
    assert oversized.status_code == 413


def test_recruiter_web_flow_creates_refreshing_comparison(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "recruiter-web.db", FakeQueue())
    try:
        workspace = client.get("/recruiter")
        submitted = client.post(
            "/recruiter/batches",
            data={"target_role": "python_backend_developer"},
            files={"file": ("candidates.csv", b"octocat\nhubot\n", "text/csv")},
            follow_redirects=False,
        )
        comparison = client.get(submitted.headers["location"])
    finally:
        client.__exit__(None, None, None)

    assert workspace.status_code == 200
    assert "Create a batch" in workspace.text
    assert submitted.status_code == 303
    assert comparison.status_code == 200
    assert "Human review required" in comparison.text
    assert "octocat" in comparison.text
    assert '<meta http-equiv="refresh" content="3">' in comparison.text


def test_recruiter_batch_creation_is_rate_limited(tmp_path: Path) -> None:
    client = create_test_client(
        tmp_path / "recruiter-rate.db",
        FakeQueue(),
        recruiter_batch_rate_limit=1,
    )
    upload = {"file": ("candidates.csv", b"octocat\n", "text/csv")}
    try:
        allowed = client.post("/v1/recruiter/batches", files=upload)
        blocked = client.post("/v1/recruiter/batches", files=upload)
    finally:
        client.__exit__(None, None, None)

    assert allowed.status_code == 202
    assert allowed.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_web_form_returns_inline_validation_error(tmp_path: Path) -> None:
    client = create_test_client(tmp_path / "web-form-invalid.db", FakeQueue())
    try:
        client.cookies.set(SESSION_COOKIE, web_session_cookie()[SESSION_COOKIE])
        response = client.post(
            "/app/analyze",
            data={
                "github_username": "-invalid--name",
                "action": "profile",
            },
        )
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 422
    assert 'class="form-error"' in response.text
    assert "Enter a valid GitHub username" in response.text


def test_web_form_requires_web_session(tmp_path: Path) -> None:
    queue = FakeQueue()
    client = create_test_client(
        tmp_path / "web-form-auth.db",
        queue,
        api_keys="developer=correct-horse-battery-staple",
    )
    payload = {
        "github_username": "octocat",
        "action": "profile",
    }
    try:
        home = client.get("/")
        missing = client.post("/app/analyze", data=payload)
        client.cookies.set(SESSION_COOKIE, web_session_cookie()[SESSION_COOKIE])
        allowed = client.post(
            "/app/analyze",
            data=payload,
            follow_redirects=False,
        )
        history = client.get("/history")
        logout = client.post("/session/logout", follow_redirects=False)
    finally:
        client.__exit__(None, None, None)

    assert 'id="clerk-sign-in"' in home.text
    assert missing.status_code == 401
    assert "Sign in with Clerk" in missing.text
    assert allowed.status_code == 303
    assert allowed.headers["location"].startswith("/reports/")
    assert history.status_code == 200
    assert "octocat" in history.text
    assert logout.status_code == 303
    assert "devdna_session=" in logout.headers["set-cookie"]
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
                    "analyzer_version": "evidence-v1",
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
        learning_response = client.get(f"/v1/analyses/{analysis_id}/learning")
        report_page = client.get(f"/reports/{analysis_id}")
        readme_page = client.get(f"/reports/{analysis_id}/readme")
        readme_download = client.get(f"/reports/{analysis_id}/readme.md")
        learning_page = client.get(f"/reports/{analysis_id}/learning")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["profile_snapshot"]["profile"]["login"] == "octocat"
    assert response.json()["evidence_snapshot"]["analyzer_version"] == ("evidence-v1")
    assert response.json()["error_message"] == "Repository collection failed"
    assert report_response.status_code == 200
    assert report_response.json()["collection_status"] == "partial"
    assert readme_response.status_code == 200
    assert readme_response.json()["github_username"] == "octocat"
    assert learning_response.status_code == 200
    assert learning_response.json()["recommendations"][-1]["kind"] == "market_signal"
    assert report_page.status_code == 200
    assert "The evidence spine" in report_page.text
    assert "Partial inspection" in report_page.text
    assert readme_page.status_code == 200
    assert "A stronger profile" in readme_page.text
    assert readme_download.status_code == 200
    assert readme_download.headers["content-type"].startswith("text/markdown")
    assert 'filename="README.md"' in readme_download.headers["content-disposition"]
    assert learning_page.status_code == 200
    assert "Learn what your portfolio cannot prove yet" in learning_page.text
    assert "GitHub Octoverse 2025" in learning_page.text
