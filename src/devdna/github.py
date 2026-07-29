from urllib.parse import quote

import httpx2

from devdna.config import Settings
from devdna.schemas import GitHubProfile, GitHubRepository, GitHubSnapshot

MAX_REPOSITORIES = 10
MAX_REPOSITORY_PAGES = 3


class GitHubUserNotFound(Exception):
    pass


class GitHubRateLimited(Exception):
    def __init__(self, reset_at: int | None) -> None:
        self.reset_at = reset_at
        super().__init__("GitHub rate limit exceeded")


def integer_header(response: httpx2.Response, name: str) -> int | None:
    value = response.headers.get(name)
    return int(value) if value and value.isdigit() else None


def select_repositories(
    repositories: list[GitHubRepository],
    limit: int = MAX_REPOSITORIES,
) -> list[GitHubRepository]:
    eligible = [
        repository
        for repository in repositories
        if not repository.fork
        and not repository.archived
        and not repository.disabled
        and repository.size > 0
    ]
    return sorted(
        eligible,
        key=lambda repository: repository.pushed_at or repository.updated_at,
        reverse=True,
    )[:limit]


class GitHubClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DevDNA",
            "X-GitHub-Api-Version": self.settings.github_api_version,
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token.get_secret_value()}"
        return headers

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=self.settings.github_api_url,
            headers=self.headers(),
            timeout=self.settings.github_timeout_seconds,
            transport=self.transport,
        )

    @staticmethod
    def raise_for_status(response: httpx2.Response, username: str) -> None:
        if response.status_code == 404:
            raise GitHubUserNotFound(username)
        if (
            response.status_code in {403, 429}
            and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise GitHubRateLimited(integer_header(response, "x-ratelimit-reset"))
        response.raise_for_status()

    async def get_profile(self, username: str) -> GitHubSnapshot:
        async with self.client() as client:
            response = await client.get(f"/users/{quote(username, safe='')}")

        self.raise_for_status(response, username)
        return GitHubSnapshot(
            profile=GitHubProfile.model_validate(response.json()),
            rate_limit_remaining=integer_header(response, "x-ratelimit-remaining"),
            rate_limit_reset=integer_header(response, "x-ratelimit-reset"),
        )

    async def get_repositories(
        self,
        username: str,
    ) -> tuple[list[GitHubRepository], int | None, int | None]:
        repositories: list[GitHubRepository] = []
        next_url: str | None = f"/users/{quote(username, safe='')}/repos"
        params: dict[str, str | int] | None = {
            "type": "owner",
            "sort": "pushed",
            "direction": "desc",
            "per_page": 100,
        }
        remaining: int | None = None
        reset: int | None = None

        async with self.client() as client:
            for _ in range(MAX_REPOSITORY_PAGES):
                if next_url is None:
                    break
                response = await client.get(next_url, params=params)
                self.raise_for_status(response, username)
                repositories.extend(
                    GitHubRepository.model_validate(repository) for repository in response.json()
                )
                remaining = integer_header(response, "x-ratelimit-remaining")
                reset = integer_header(response, "x-ratelimit-reset")
                selected = select_repositories(repositories)
                if len(selected) == MAX_REPOSITORIES:
                    return selected, remaining, reset
                next_url = response.links.get("next", {}).get("url")
                params = None

        return select_repositories(repositories), remaining, reset

    async def get_snapshot(self, username: str) -> GitHubSnapshot:
        snapshot = await self.get_profile(username)
        repositories, remaining, reset = await self.get_repositories(username)
        return GitHubSnapshot(
            profile=snapshot.profile,
            repositories=repositories,
            rate_limit_remaining=remaining
            if remaining is not None
            else snapshot.rate_limit_remaining,
            rate_limit_reset=reset if reset is not None else snapshot.rate_limit_reset,
        )
