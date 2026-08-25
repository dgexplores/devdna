from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from devdna.activity import (
    activity_window_label,
    classify_commit,
    extract_activity_insights,
)


def _push_event(
    *,
    repo: str,
    messages: list[str],
    days_ago: int,
    username: str = "octocat",
) -> dict[str, object]:
    occurred = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "type": "PushEvent",
        "repo": {"name": repo},
        "created_at": occurred.isoformat(),
        "payload": {
            "commits": [
                {
                    "sha": f"sha{i}{repo.split('/')[0]}",
                    "message": message,
                }
                for i, message in enumerate(messages)
            ]
        },
    }


def test_classify_commit_kinds() -> None:
    assert classify_commit("feat: add JWT refresh flow") == ("feature", True)
    assert classify_commit("fix(auth): reject expired tokens") == ("fix", True)
    assert classify_commit("test: cover rate limiter") == ("tests", True)
    assert classify_commit("docs: document /metrics endpoint") == ("docs", True)
    assert classify_commit("perf: cache ETag responses") == ("performance", True)
    assert classify_commit("Refactor session signing into its own module with tests") == (
        "refactor",
        True,
    )
    assert classify_commit("chore: update dependencies")[1] is False
    assert classify_commit("wip")[1] is False
    assert classify_commit("Merge branch 'main' of github.com:x/y")[1] is False
    assert classify_commit("Bump httpx from 0.27 to 0.28")[1] is False
    assert classify_commit("asdf")[1] is False


def test_activity_extraction_counts_meaningful_work() -> None:
    events: list[dict[str, object]] = [
        _push_event(
            repo="octocat/api",
            messages=[
                "feat: pagination for repository listing",
                "fix: correct timezone drift in scheduler",
                "wip",
                "Merge branch 'develop'",
            ],
            days_ago=3,
        ),
        _push_event(
            repo="octocat/api",
            messages=["test: add report contract fixtures", "refactor: split evidence rules"],
            days_ago=10,
        ),
        {
            "type": "PullRequestEvent",
            "repo": {"name": "other/lib"},
            "created_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
            "payload": {
                "action": "closed",
                "pull_request": {
                    "title": "Add retry with backoff to client",
                    "merged": True,
                    "html_url": "https://github.com/other/lib/pull/12",
                },
            },
        },
        {
            "type": "PullRequestEvent",
            "repo": {"name": "octocat/api"},
            "created_at": (datetime.now(UTC) - timedelta(days=6)).isoformat(),
            "payload": {"action": "opened", "pull_request": {"title": "WIP feature"}},
        },
        {
            "type": "IssuesEvent",
            "repo": {"name": "octocat/api"},
            "created_at": (datetime.now(UTC) - timedelta(days=7)).isoformat(),
            "payload": {"action": "opened", "issue": {"title": "Bug"}},
        },
    ]

    insights = extract_activity_insights(events, "octocat")
    assert insights is not None
    assert insights.commits_analyzed == 6
    assert insights.meaningful_commits == 4
    assert insights.features_shipped == 1
    assert insights.fixes_landed == 1
    assert insights.tests_and_docs == 1
    assert insights.refactors == 1
    assert insights.opened_pull_requests == 1
    assert insights.issues_opened == 1
    assert len(insights.merged_pull_requests) == 1
    merged = insights.merged_pull_requests[0]
    assert merged.title == "Add retry with backoff to client"
    assert merged.repository == "other/lib"
    assert merged.url == "https://github.com/other/lib/pull/12"
    # open-source event share: 1 of 5 events targets another owner
    assert insights.open_source_share == 20
    assert "octocat/api" in insights.repositories_touched
    assert "other/lib" in insights.repositories_touched
    first_notable = insights.notable_commits[0]
    assert first_notable.kind in {"feature", "fix", "tests", "refactor"}
    assert first_notable.url is not None
    assert first_notable.url.startswith("https://github.com/octocat/api/commit/")
    label = activity_window_label(insights)
    assert label.startswith("last ")
    assert "no vanity" not in label


def test_bot_and_noise_never_count_as_meaningful() -> None:
    events = [
        _push_event(
            repo="octocat/app",
            messages=[
                "Bump pytest from 8.0 to 8.1 [bot]",
                "chore: update dependencies",
                "initial commit",
            ],
            days_ago=2,
        )
    ]
    insights = extract_activity_insights(events, "octocat")
    assert insights is not None
    assert insights.commits_analyzed == 3
    assert insights.meaningful_commits == 0
    assert insights.notable_commits == []


def test_empty_or_invalid_events_return_none() -> None:
    assert extract_activity_insights([], "octocat") is None
    watch_only: list[dict[str, object]] = [{"type": "WatchEvent"}]
    invalid_events = cast("list[dict[str, Any]]", watch_only)
    assert extract_activity_insights(invalid_events, "octocat") is None


def test_report_page_renders_recent_impact_section(tmp_path: Path) -> None:
    import asyncio

    from conftest import create_test_client
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from devdna.database import Base
    from devdna.models import AnalysisRun
    from devdna.reports import generate_report
    from devdna.schemas import (
        ActivityInsights,
        EvidenceItem,
        EvidenceSnapshot,
        EvidenceSource,
        MergedPullRequest,
        NotableCommit,
    )

    evidence = EvidenceSnapshot(
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
    now = datetime.now(UTC)
    activity = ActivityInsights(
        sample_start=now - timedelta(days=5),
        sample_end=now,
        commits_analyzed=9,
        meaningful_commits=4,
        features_shipped=2,
        fixes_landed=1,
        tests_and_docs=1,
        open_source_share=25,
        opened_pull_requests=3,
        repositories_touched=["octocat/backend", "other/lib"],
        notable_commits=[
            NotableCommit(
                message="feat: pagination for repository listing",
                repository="octocat/backend",
                url="https://github.com/octocat/backend/commit/abc123",
                occurred_at=now - timedelta(days=2),
                kind="feature",
            )
        ],
        merged_pull_requests=[
            MergedPullRequest(
                title="Add retry with backoff to client",
                repository="other/lib",
                url="https://github.com/other/lib/pull/12",
                occurred_at=now - timedelta(days=4),
            )
        ],
    )

    database_path = tmp_path / "impact.db"
    client = create_test_client(database_path)
    try:
        analysis_id = client.post(
            "/v1/analyses",
            json={"github_username": "octocat", "target_role": "python_backend_developer"},
        ).json()["id"]
    finally:
        client.__exit__(None, None, None)

    async def seed() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            analysis = await session.get(AnalysisRun, analysis_id)
            assert analysis is not None
            analysis.status = "completed"
            analysis.profile_snapshot = {
                "profile": {"login": "octocat"},
                "activity": activity.model_dump(mode="json"),
            }
            analysis.evidence_snapshot = evidence.model_dump(mode="json")
            analysis.report_snapshot = generate_report(evidence, "completed").model_dump(
                mode="json"
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())

    client = create_test_client(database_path)
    try:
        page = client.get(f"/reports/{analysis_id}")
    finally:
        client.__exit__(None, None, None)

    assert page.status_code == 200
    assert "Recent impact" in page.text
    assert "feat: pagination for repository listing" in page.text
    assert "kind-feature" in page.text
    assert "Add retry with backoff to client" in page.text
    assert "open-source share" in page.text
    assert "commit-row" in page.text
