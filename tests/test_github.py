import asyncio

import httpx2
import pytest
from pydantic import SecretStr

from devdna.config import Settings
from devdna.github import GitHubClient, GitHubRateLimited, GitHubUserNotFound

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
