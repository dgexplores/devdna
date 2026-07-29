import asyncio

import httpx2
import pytest
from pydantic import SecretStr

from devdna.config import Settings
from devdna.github import (
    GitHubClient,
    GitHubRateLimited,
    GitHubUserNotFound,
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


def test_get_snapshot_paginates_until_it_finds_eligible_repositories() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/users/octocat":
            return httpx2.Response(200, json=PROFILE)
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
