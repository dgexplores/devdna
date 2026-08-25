import asyncio
import base64

import httpx2
import pytest
from pydantic import SecretStr

from devdna.config import Settings
from devdna.github import (
    GitHubClient,
    GitHubPartialResult,
    GitHubRateLimited,
    GitHubTransientError,
    GitHubUserNotFound,
    aggregate_contributions,
    select_repositories,
)
from devdna.schemas import GitHubRepository

PROFILE = {
    "login": "octocat",
    "id": 1,
    "avatar_url": "https://github.com/images/error/octocat_happy.gif",
    "html_url": "https://github.com/octocat",
    "name": "The Octocat",
    "company": "GitHub",
    "blog": "https://github.blog",
    "location": "San Francisco",
    "bio": "GitHub mascot",
    "public_repos": 8,
    "followers": 20,
    "following": 0,
    "created_at": "2011-01-25T18:44:36Z",
    "updated_at": "2026-01-01T00:00:00Z",
}

REPOSITORY = {
    "id": 1,
    "name": "project",
    "full_name": "octocat/project",
    "html_url": "https://github.com/octocat/project",
    "description": "A project",
    "fork": False,
    "archived": False,
    "disabled": False,
    "language": "Python",
    "topics": ["fastapi"],
    "size": 100,
    "stargazers_count": 5,
    "forks_count": 1,
    "open_issues_count": 0,
    "default_branch": "main",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "pushed_at": "2026-01-01T00:00:00Z",
}


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        assert ex == 86400
        self.values[key] = value


def settings() -> Settings:
    return Settings(environment="test", github_token=SecretStr("test-token"))


def test_get_profile_returns_snapshot_and_rate_limit() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/users/octocat"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        return httpx2.Response(
            200,
            json=PROFILE,
            headers={"x-ratelimit-remaining": "4999", "x-ratelimit-reset": "123456"},
        )

    client = GitHubClient(settings(), httpx2.MockTransport(handler))
    snapshot = asyncio.run(client.get_profile("octocat"))

    assert snapshot.profile.login == "octocat"
    assert snapshot.rate_limit_remaining == 4999
    assert snapshot.rate_limit_reset == 123456


def test_get_profile_reports_missing_user() -> None:
    transport = httpx2.MockTransport(lambda _: httpx2.Response(404))

    with pytest.raises(GitHubUserNotFound):
        asyncio.run(GitHubClient(settings(), transport).get_profile("missing"))


def test_get_profile_reports_rate_limit_reset() -> None:
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "123456"},
        )
    )

    with pytest.raises(GitHubRateLimited, match="rate limit"):
        asyncio.run(GitHubClient(settings(), transport).get_profile("octocat"))


def test_get_profile_reuses_cached_body_after_etag_validation() -> None:
    requests = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx2.Response(
                200,
                json=PROFILE,
                headers={"etag": '"profile-v1"', "x-ratelimit-remaining": "58"},
            )
        assert request.headers["if-none-match"] == '"profile-v1"'
        return httpx2.Response(304)

    client = GitHubClient(
        settings(),
        httpx2.MockTransport(handler),
        cache=MemoryCache(),
    )
    first = asyncio.run(client.get_profile("octocat"))
    second = asyncio.run(client.get_profile("octocat"))

    assert first.profile == second.profile
    assert second.rate_limit_remaining == 58
    assert requests == 2


def test_get_profile_marks_server_errors_as_transient() -> None:
    transport = httpx2.MockTransport(lambda _: httpx2.Response(503))

    with pytest.raises(GitHubTransientError, match="temporary"):
        asyncio.run(GitHubClient(settings(), transport).get_profile("octocat"))


def test_get_snapshot_paginates_until_it_finds_eligible_repositories() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(200, json=PROFILE)
        if request.url.path == "/users/octocat/events/public":
            return httpx2.Response(200, json=[])
        if request.url.path == "/users/octocat/orgs":
            return httpx2.Response(200, json=[{"login": "github"}])
        if request.url.path == "/repos/octocat/new/git/trees/main":
            return httpx2.Response(200, json={"tree": [], "truncated": False})
        if request.url.path == "/repos/octocat/new/languages":
            return httpx2.Response(200, json={"Python": 500})
        if request.url.path.endswith("/commits"):
            return httpx2.Response(200, json=[])
        if request.url.params.get("page") == "2":
            repository = {**REPOSITORY, "id": 4, "name": "new", "full_name": "octocat/new"}
            return httpx2.Response(
                200,
                json=[repository],
                headers={"x-ratelimit-remaining": "57", "x-ratelimit-reset": "123456"},
            )
        assert request.url.params["type"] == "owner"
        assert request.url.params["sort"] == "pushed"
        return httpx2.Response(
            200,
            json=[
                {**REPOSITORY, "id": 2, "name": "fork", "fork": True},
                {**REPOSITORY, "id": 3, "name": "archived", "archived": True},
            ],
            headers={
                "link": '<https://api.github.com/users/octocat/repos?page=2>; rel="next"',
            },
        )

    snapshot = asyncio.run(
        GitHubClient(settings(), httpx2.MockTransport(handler)).get_snapshot("octocat")
    )

    assert [repository.name for repository in snapshot.repositories] == ["new"]
    assert snapshot.rate_limit_remaining == 57
    assert snapshot.organizations == ["github"]
    assert snapshot.repositories[0].languages == {"Python": 500}


def test_get_snapshot_collects_file_tree_and_manifest_dependencies() -> None:
    manifest = """
[project]
dependencies = ["fastapi>=0.100", "SQLAlchemy~=2.0"]

[project.optional-dependencies]
test = ["pytest>=8"]
"""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(200, json=PROFILE)
        if request.url.path == "/users/octocat/events/public":
            return httpx2.Response(200, json=[])
        if request.url.path == "/users/octocat/orgs":
            return httpx2.Response(200, json=[])
        if request.url.path == "/users/octocat/repos":
            return httpx2.Response(200, json=[REPOSITORY])
        if request.url.path == "/repos/octocat/project/git/trees/main":
            return httpx2.Response(
                200,
                json={
                    "tree": [
                        {"path": "pyproject.toml", "type": "blob"},
                        {"path": "src/main.py", "type": "blob"},
                        {"path": "tests/test_main.py", "type": "blob"},
                        {"path": ".github/workflows/ci.yml", "type": "blob"},
                        {"path": "Dockerfile", "type": "blob"},
                        {"path": "README.md", "type": "blob"},
                        {"path": "alembic.ini", "type": "blob"},
                    ],
                    "truncated": False,
                },
            )
        if request.url.path == "/repos/octocat/project/contents/pyproject.toml":
            return httpx2.Response(
                200,
                json={
                    "encoding": "base64",
                    "size": len(manifest),
                    "content": base64.b64encode(manifest.encode()).decode(),
                },
                headers={"x-ratelimit-remaining": "55"},
            )
        if request.url.path == "/repos/octocat/project/languages":
            return httpx2.Response(
                200,
                json={"Python": 900, "HTML": 100},
                headers={"x-ratelimit-remaining": "55"},
            )
        if request.url.path.endswith("/commits"):
            return httpx2.Response(
                200,
                json=[],
                headers={"x-ratelimit-remaining": "55"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    snapshot = asyncio.run(
        GitHubClient(settings(), httpx2.MockTransport(handler)).get_snapshot("octocat")
    )

    assert len(snapshot.inspections) == 1
    inspection = snapshot.inspections[0]
    assert inspection.repository_full_name == "octocat/project"
    assert inspection.manifest_paths == ["pyproject.toml"]
    assert inspection.dependencies == ["fastapi", "pytest", "sqlalchemy"]
    assert inspection.tree_truncated is False
    assert snapshot.rate_limit_remaining == 55
    assert snapshot.repositories[0].languages == {"Python": 900, "HTML": 100}


def test_get_snapshot_returns_partial_when_file_tree_fails() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(200, json=PROFILE)
        if request.url.path == "/users/octocat/repos":
            return httpx2.Response(200, json=[REPOSITORY])
        return httpx2.Response(503)

    with pytest.raises(GitHubPartialResult) as raised:
        asyncio.run(GitHubClient(settings(), httpx2.MockTransport(handler)).get_snapshot("octocat"))

    assert raised.value.snapshot.repositories[0].full_name == "octocat/project"
    assert raised.value.snapshot.inspections == []
    assert raised.value.warning == "octocat/project: file tree could not be inspected"


def test_get_snapshot_preserves_collected_data_when_repository_page_fails() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(
                200,
                json=PROFILE,
                headers={"x-ratelimit-remaining": "59"},
            )
        if request.url.params.get("page") == "2":
            return httpx2.Response(503)
        return httpx2.Response(
            200,
            json=[REPOSITORY],
            headers={
                "link": '<https://api.github.com/users/octocat/repos?page=2>; rel="next"',
                "x-ratelimit-remaining": "58",
            },
        )

    with pytest.raises(GitHubPartialResult) as raised:
        asyncio.run(GitHubClient(settings(), httpx2.MockTransport(handler)).get_snapshot("octocat"))

    assert raised.value.snapshot.profile.login == "octocat"
    assert [repository.name for repository in raised.value.snapshot.repositories] == ["project"]
    assert raised.value.snapshot.rate_limit_remaining == 58
    assert raised.value.warning == ("Repository collection failed; profile data is still available")


def test_get_snapshot_returns_partial_profile_at_repository_rate_limit() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(200, json=PROFILE)
        return httpx2.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "123456"},
        )

    with pytest.raises(GitHubPartialResult) as raised:
        asyncio.run(GitHubClient(settings(), httpx2.MockTransport(handler)).get_snapshot("octocat"))

    assert raised.value.snapshot.profile.login == "octocat"
    assert raised.value.snapshot.repositories == []
    assert raised.value.snapshot.rate_limit_reset == 123456
    assert raised.value.warning == (
        "Repository collection stopped by GitHub rate limit; retry after 123456"
    )


def test_repository_selection_filters_and_caps_results() -> None:
    repositories = [
        GitHubRepository.model_validate(
            {
                **REPOSITORY,
                "id": index,
                "name": f"project-{index}",
                "full_name": f"octocat/project-{index}",
                "pushed_at": f"2026-01-{index + 1:02d}T00:00:00Z",
            }
        )
        for index in range(12)
    ]
    repositories.append(
        GitHubRepository.model_validate({**REPOSITORY, "id": 99, "name": "empty", "size": 0})
    )

    selected = select_repositories(repositories)

    assert len(selected) == 10
    assert selected[0].name == "project-11"
    assert all(repository.name != "empty" for repository in selected)


def test_aggregate_contributions_counts_own_and_open_source_activity() -> None:
    events = [
        {
            "type": "PushEvent",
            "repo": {"name": "octocat/project"},
            "created_at": "2026-07-01T10:00:00Z",
        },
        {
            "type": "PushEvent",
            "repo": {"name": "octocat/project"},
            "created_at": "2026-07-02T10:00:00Z",
        },
        {
            "type": "PullRequestEvent",
            "repo": {"name": "other/opensource"},
            "created_at": "2026-07-03T10:00:00Z",
        },
        {
            "type": "ForkEvent",
            "repo": {"name": "third/repo"},
            "created_at": "2026-07-04T10:00:00Z",
        },
    ]

    result = aggregate_contributions(events, "octocat", 42, 123456)

    assert result.push_events == 2
    assert result.pull_request_events == 1
    assert result.distinct_repositories == 3
    assert result.open_source_events == 1
    assert result.open_source_repositories == ["other/opensource"]
    assert result.days_span == 3
    assert result.rate_limit_remaining == 42
    assert len(result.weekly) == 4


def test_aggregate_contributions_returns_none_when_empty() -> None:
    client = GitHubClient(
        settings(),
        httpx2.MockTransport(lambda r: httpx2.Response(404)),
    )
    contributions, events, remaining, reset = asyncio.run(client.get_contributions("octocat"))

    assert contributions is None
    assert events == []
    assert remaining is None
    assert reset is None
