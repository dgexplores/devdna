import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import httpx2

from devdna.config import Settings
from devdna.schemas import GitHubProfile, GitHubRepository, GitHubSnapshot

MAX_REPOSITORIES = 10
MAX_REPOSITORY_PAGES = 3
CACHE_TTL_SECONDS = 86400


class GitHubUserNotFound(Exception):
    pass


class GitHubRateLimited(Exception):
    def __init__(self, reset_at: int | None) -> None:
        self.reset_at = reset_at
        super().__init__("GitHub rate limit exceeded")


class GitHubTransientError(Exception):
    pass


class GitHubPartialResult(Exception):
    def __init__(self, snapshot: GitHubSnapshot, warning: str) -> None:
        self.snapshot = snapshot
        self.warning = warning
        super().__init__(warning)


class RepositoryCollectionFailed(Exception):
    def __init__(
        self,
        repositories: list[GitHubRepository],
        rate_limit_remaining: int | None,
        rate_limit_reset: int | None,
        warning: str,
    ) -> None:
        self.repositories = repositories
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset
        self.warning = warning
        super().__init__(warning)


class ResponseCache(Protocol):
    async def get(self, key: str) -> bytes | str | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> Any: ...


@dataclass(frozen=True)
class CachedJson:
    body: Any
    etag: str | None
    link: str | None
    rate_limit_remaining: int | None
    rate_limit_reset: int | None


def integer_header(response: httpx2.Response, name: str) -> int | None:
    value = response.headers.get(name)
    return int(value) if value and value.isdigit() else None


def next_link(link: str | None) -> str | None:
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<") + 1 : part.find(">")]
    return None


def decode_cached(value: bytes | str | None) -> CachedJson | None:
    if value is None:
        return None
    try:
        data = json.loads(value)
        return CachedJson(
            body=data["body"],
            etag=data["etag"],
            link=data["link"],
            rate_limit_remaining=data["rate_limit_remaining"],
            rate_limit_reset=data["rate_limit_reset"],
        )
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


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
        cache: ResponseCache | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.cache = cache

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
        if response.status_code in {403, 429} or response.status_code >= 500:
            raise GitHubTransientError(f"temporary GitHub response: {response.status_code}")
        response.raise_for_status()

    async def get_json(
        self,
        client: httpx2.AsyncClient,
        url: str,
        username: str,
        params: Mapping[str, str | int] | None = None,
    ) -> CachedJson:
        fingerprint = hashlib.sha256(f"{url}?{urlencode(params or {})}".encode()).hexdigest()
        cache_key = f"github:{self.settings.github_api_version}:{fingerprint}"
        cached = decode_cached(await self.cache.get(cache_key)) if self.cache else None
        headers = {"If-None-Match": cached.etag} if cached and cached.etag else None
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx2.RequestError as error:
            raise GitHubTransientError("GitHub request failed") from error

        if response.status_code == 304:
            if cached is None:
                raise GitHubTransientError("GitHub returned 304 without a cached response")
            return cached

        self.raise_for_status(response, username)
        result = CachedJson(
            body=response.json(),
            etag=response.headers.get("etag"),
            link=response.headers.get("link"),
            rate_limit_remaining=integer_header(response, "x-ratelimit-remaining"),
            rate_limit_reset=integer_header(response, "x-ratelimit-reset"),
        )
        if self.cache and result.etag:
            await self.cache.set(
                cache_key,
                json.dumps(
                    {
                        "body": result.body,
                        "etag": result.etag,
                        "link": result.link,
                        "rate_limit_remaining": result.rate_limit_remaining,
                        "rate_limit_reset": result.rate_limit_reset,
                    }
                ),
                ex=CACHE_TTL_SECONDS,
            )
        return result

    async def get_profile(self, username: str) -> GitHubSnapshot:
        async with self.client() as client:
            response = await self.get_json(
                client,
                f"/users/{quote(username, safe='')}",
                username,
            )

        return GitHubSnapshot(
            profile=GitHubProfile.model_validate(response.body),
            rate_limit_remaining=response.rate_limit_remaining,
            rate_limit_reset=response.rate_limit_reset,
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
                try:
                    response = await self.get_json(client, next_url, username, params)
                except GitHubRateLimited as error:
                    reset = error.reset_at or reset
                    warning = (
                        f"Repository collection stopped by GitHub rate limit; retry after {reset}"
                        if reset
                        else "Repository collection stopped by GitHub rate limit"
                    )
                    raise RepositoryCollectionFailed(
                        select_repositories(repositories),
                        remaining,
                        reset,
                        warning,
                    ) from error
                except (GitHubTransientError, GitHubUserNotFound, httpx2.HTTPStatusError) as error:
                    raise RepositoryCollectionFailed(
                        select_repositories(repositories),
                        remaining,
                        reset,
                        "Repository collection failed; profile data is still available",
                    ) from error
                repositories.extend(
                    GitHubRepository.model_validate(repository) for repository in response.body
                )
                remaining = response.rate_limit_remaining
                reset = response.rate_limit_reset
                selected = select_repositories(repositories)
                if len(selected) == MAX_REPOSITORIES:
                    return selected, remaining, reset
                next_url = next_link(response.link)
                params = None

        return select_repositories(repositories), remaining, reset

    async def get_snapshot(self, username: str) -> GitHubSnapshot:
        snapshot = await self.get_profile(username)
        try:
            repositories, remaining, reset = await self.get_repositories(username)
        except RepositoryCollectionFailed as error:
            raise GitHubPartialResult(
                GitHubSnapshot(
                    profile=snapshot.profile,
                    repositories=error.repositories,
                    rate_limit_remaining=error.rate_limit_remaining
                    if error.rate_limit_remaining is not None
                    else snapshot.rate_limit_remaining,
                    rate_limit_reset=error.rate_limit_reset
                    if error.rate_limit_reset is not None
                    else snapshot.rate_limit_reset,
                ),
                error.warning,
            ) from error
        return GitHubSnapshot(
            profile=snapshot.profile,
            repositories=repositories,
            rate_limit_remaining=remaining
            if remaining is not None
            else snapshot.rate_limit_remaining,
            rate_limit_reset=reset if reset is not None else snapshot.rate_limit_reset,
        )
