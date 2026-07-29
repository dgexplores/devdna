from urllib.parse import quote

import httpx2

from devdna.config import Settings
from devdna.schemas import GitHubProfile, GitHubSnapshot


class GitHubUserNotFound(Exception):
    pass


class GitHubRateLimited(Exception):
    def __init__(self, reset_at: int | None) -> None:
        self.reset_at = reset_at
        super().__init__("GitHub rate limit exceeded")


def integer_header(response: httpx2.Response, name: str) -> int | None:
    value = response.headers.get(name)
    return int(value) if value and value.isdigit() else None


class GitHubClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def get_profile(self, username: str) -> GitHubSnapshot:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DevDNA",
            "X-GitHub-Api-Version": self.settings.github_api_version,
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token.get_secret_value()}"

        async with httpx2.AsyncClient(
            base_url=self.settings.github_api_url,
            headers=headers,
            timeout=self.settings.github_timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.get(f"/users/{quote(username, safe='')}")

        if response.status_code == 404:
            raise GitHubUserNotFound(username)
        if (
            response.status_code in {403, 429}
            and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise GitHubRateLimited(integer_header(response, "x-ratelimit-reset"))
        response.raise_for_status()
        return GitHubSnapshot(
            profile=GitHubProfile.model_validate(response.json()),
            rate_limit_remaining=integer_header(response, "x-ratelimit-remaining"),
            rate_limit_reset=integer_header(response, "x-ratelimit-reset"),
        )
