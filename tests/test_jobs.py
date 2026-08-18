import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.database import Base
from devdna.github import GitHubPartialResult, GitHubTransientError
from devdna.jobs import collect_profile
from devdna.models import AnalysisRun
from devdna.schemas import (
    GitHubProfile,
    GitHubRepository,
    GitHubSnapshot,
    RepositoryInspection,
)


def test_collect_profile_completes_analysis(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        analysis = AnalysisRun(
            id="analysis-id",
            github_username="octocat",
            target_role="python_backend_developer",
            status="queued",
        )
        async with sessions() as session:
            session.add(analysis)
            await session.commit()

        async def fetch_profile(_: str) -> GitHubSnapshot:
            return GitHubSnapshot(
                profile=GitHubProfile(
                    login="octocat",
                    id=1,
                    avatar_url="https://github.com/octocat.png",
                    html_url="https://github.com/octocat",
                    public_repos=8,
                    followers=20,
                    following=0,
                    created_at=datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                repositories=[
                    GitHubRepository(
                        id=2,
                        name="project",
                        full_name="octocat/project",
                        html_url="https://github.com/octocat/project",
                        fork=False,
                        archived=False,
                        disabled=False,
                        language="Python",
                        size=100,
                        stargazers_count=5,
                        forks_count=1,
                        open_issues_count=0,
                        default_branch="main",
                        created_at=datetime(2024, 1, 1, tzinfo=UTC),
                        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                        pushed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                ],
                inspections=[
                    RepositoryInspection(
                        repository_full_name="octocat/project",
                        default_branch="main",
                        file_paths=["pyproject.toml", "src/main.py"],
                        manifest_paths=["pyproject.toml"],
                        dependencies=["fastapi"],
                    )
                ],
                rate_limit_remaining=59,
                rate_limit_reset=123456,
            )

        await collect_profile("analysis-id", sessions, fetch_profile)

        async with sessions() as session:
            result = await session.get(AnalysisRun, "analysis-id")
            assert result is not None
            assert result.status == "completed"
            assert result.profile_snapshot is not None
            assert result.profile_snapshot["profile"]["login"] == "octocat"
            assert result.profile_snapshot["repositories"][0]["name"] == "project"
            assert result.evidence_snapshot is not None
            assert result.evidence_snapshot["analyzer_version"] == ("evidence-v1")
            assert result.evidence_snapshot["items"][0]["key"] == "python.project"
            assert result.report_snapshot is not None
            assert result.report_snapshot["report_version"] == "python-backend-report-v1"
            assert result.report_snapshot["requirements_met"] == 2
        await engine.dispose()

    asyncio.run(scenario())


def test_collect_profile_completes_react_analysis(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'react.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        analysis = AnalysisRun(
            id="react-analysis-id",
            github_username="octocat",
            target_role="frontend_react_developer",
            status="queued",
        )
        async with sessions() as session:
            session.add(analysis)
            await session.commit()

        async def fetch_profile(_: str) -> GitHubSnapshot:
            return GitHubSnapshot(
                profile=GitHubProfile(
                    login="octocat",
                    id=1,
                    avatar_url="https://github.com/octocat.png",
                    html_url="https://github.com/octocat",
                    public_repos=8,
                    followers=20,
                    following=0,
                    created_at=datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                repositories=[
                    GitHubRepository(
                        id=3,
                        name="react-app",
                        full_name="octocat/react-app",
                        html_url="https://github.com/octocat/react-app",
                        fork=False,
                        archived=False,
                        disabled=False,
                        language="TypeScript",
                        size=100,
                        stargazers_count=5,
                        forks_count=1,
                        open_issues_count=0,
                        default_branch="main",
                        created_at=datetime(2024, 1, 1, tzinfo=UTC),
                        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                        pushed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                ],
                inspections=[
                    RepositoryInspection(
                        repository_full_name="octocat/react-app",
                        default_branch="main",
                        file_paths=[
                            "package.json",
                            "tsconfig.json",
                            "src/main.tsx",
                            "src/App.test.tsx",
                        ],
                        manifest_paths=["package.json"],
                        dependencies=["@testing-library/react", "react", "react-dom", "vitest"],
                    )
                ],
                rate_limit_remaining=59,
                rate_limit_reset=123456,
            )

        await collect_profile("react-analysis-id", sessions, fetch_profile)

        async with sessions() as session:
            result = await session.get(AnalysisRun, "react-analysis-id")
            assert result is not None
            assert result.status == "completed"
            assert result.evidence_snapshot is not None
            assert result.evidence_snapshot["rubric_version"] == "frontend_react_developer:v1"
            assert result.evidence_snapshot["items"][0]["key"] == "react.app"
            assert result.report_snapshot is not None
            assert result.report_snapshot["report_version"] == "frontend-react-report-v1"
            assert result.report_snapshot["requirements_total"] == 8
            assert result.report_snapshot["target_role"] == "frontend_react_developer"
        await engine.dispose()

    asyncio.run(scenario())


def test_collect_profile_preserves_retryable_failure(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                AnalysisRun(
                    id="retry-id",
                    github_username="octocat",
                    target_role="python_backend_developer",
                    status="queued",
                )
            )
            await session.commit()

        async def fail(_: str) -> GitHubSnapshot:
            raise GitHubTransientError("temporary")

        with pytest.raises(GitHubTransientError):
            await collect_profile("retry-id", sessions, fail)

        async with sessions() as session:
            result = await session.get(AnalysisRun, "retry-id")
            assert result is not None
            assert result.status == "failed"
            assert result.error_message == "Temporary GitHub failure; automatic retry scheduled"
        await engine.dispose()

    asyncio.run(scenario())


def test_collect_profile_saves_partial_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'partial.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                AnalysisRun(
                    id="partial-id",
                    github_username="octocat",
                    target_role="python_backend_developer",
                    status="queued",
                )
            )
            await session.commit()

        partial_snapshot = GitHubSnapshot(
            profile=GitHubProfile(
                login="octocat",
                id=1,
                avatar_url="https://github.com/octocat.png",
                html_url="https://github.com/octocat",
                public_repos=8,
                followers=20,
                following=0,
                created_at=datetime(2011, 1, 25, 18, 44, 36, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            rate_limit_remaining=0,
            rate_limit_reset=123456,
        )

        async def return_partial(_: str) -> GitHubSnapshot:
            raise GitHubPartialResult(
                partial_snapshot,
                "Repository collection stopped by GitHub rate limit; retry after 123456",
            )

        await collect_profile("partial-id", sessions, return_partial)

        async with sessions() as session:
            result = await session.get(AnalysisRun, "partial-id")
            assert result is not None
            assert result.status == "partial"
            assert result.profile_snapshot is not None
            assert result.profile_snapshot["profile"]["login"] == "octocat"
            assert result.report_snapshot is not None
            assert result.report_snapshot["collection_status"] == "partial"
            assert result.report_snapshot["warning"] == (
                "Repository collection stopped by GitHub rate limit; retry after 123456"
            )
            assert result.error_message == (
                "Repository collection stopped by GitHub rate limit; retry after 123456"
            )
        await engine.dispose()

    asyncio.run(scenario())
