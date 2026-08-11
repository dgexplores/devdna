import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import httpx2

from devdna.config import Settings
from devdna.evidence import extract_dependencies
from devdna.schemas import (
    ContributionWeek,
    GitHubContributions,
    GitHubProfile,
    GitHubRepository,
    GitHubSnapshot,
    RepositoryInspection,
)

MAX_REPOSITORIES = 10
MAX_REPOSITORY_PAGES = 3
MAX_EVENT_PAGES = 3
MAX_EVENTS = 300
CACHE_TTL_SECONDS = 86400
MAX_TREE_ENTRIES = 5000
MAX_MANIFESTS_PER_REPOSITORY = 2
MAX_MANIFEST_BYTES = 100_000
MANIFEST_NAMES = {
    "pipfile",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
}
CONTRIBUTIONS_SCHEMA_VERSION = "1"


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


def repository_from_payload(payload: Any) -> GitHubRepository:
    if not isinstance(payload, dict):
        raise ValueError("invalid repository payload")
    normalized = dict(payload)
    license_info = payload.get("license")
    normalized["license_name"] = (
        license_info.get("spdx_id")
        if isinstance(license_info, dict) and license_info.get("spdx_id")
        else None
    )
    normalized.pop("license", None)
    return GitHubRepository.model_validate(normalized)


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


def aggregate_languages(repositories: list[GitHubRepository]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repository in repositories:
        for name, bytes_count in repository.languages.items():
            totals[name] = totals.get(name, 0) + bytes_count
    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))


def summarize_warnings(warnings: list[str]) -> str:
    visible = warnings[:3]
    if len(warnings) > len(visible):
        visible.append(f"{len(warnings) - len(visible)} additional repository inspections failed")
    return "; ".join(visible)


def aggregate_contributions(
    events: list[dict[str, Any]],
    username: str,
    rate_limit_remaining: int | None = None,
    rate_limit_reset: int | None = None,
) -> GitHubContributions:
    push_events = 0
    pull_request_events = 0
    distinct_repositories: set[str] = set()
    open_source_repositories: set[str] = set()
    open_source_events = 0
    weekly: dict[str, dict[str, int]] = {}
    created_at: list[datetime] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        repo = event.get("repo")
        repo_name = repo.get("name") if isinstance(repo, dict) else None
        if not isinstance(repo_name, str) or "/" not in repo_name:
            continue
        created = event.get("created_at")
        created_dt: datetime | None = None
        if isinstance(created, str):
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                created_dt = None
        if event_type == "PushEvent":
            push_events += 1
            distinct_repositories.add(repo_name)
            owner = repo_name.split("/", 1)[0]
            if owner.lower() != username.lower():
                open_source_events += 1
                open_source_repositories.add(repo_name)
        elif event_type in {"PullRequestEvent", "PullRequestReviewEvent"}:
            pull_request_events += 1
            distinct_repositories.add(repo_name)
            owner = repo_name.split("/", 1)[0]
            if owner.lower() != username.lower():
                open_source_events += 1
                open_source_repositories.add(repo_name)
        elif event_type == "ForkEvent":
            distinct_repositories.add(repo_name)
        if created_dt is not None:
            created_at.append(created_dt)
            week_key = created_dt.strftime("%Y-%m-%d")
            week = weekly.setdefault(week_key, {"push": 0, "pr": 0})
            if event_type == "PushEvent":
                week["push"] += 1
            elif event_type in {"PullRequestEvent", "PullRequestReviewEvent"}:
                week["pr"] += 1

    if not created_at:
        return GitHubContributions(
            schema_version=CONTRIBUTIONS_SCHEMA_VERSION,
            sample_start=datetime.now(UTC),
            sample_end=datetime.now(UTC),
            days_span=0,
            total_events=len(events),
            push_events=push_events,
            pull_request_events=pull_request_events,
            distinct_repositories=len(distinct_repositories),
            open_source_repositories=sorted(open_source_repositories),
            open_source_events=open_source_events,
            rate_limit_remaining=rate_limit_remaining,
            rate_limit_reset=rate_limit_reset,
        )

    sample_start = min(created_at)
    sample_end = max(created_at)
    weeks = [
        ContributionWeek(
            week_start=week,
            push_count=counts["push"],
            pull_request_count=counts["pr"],
        )
        for week, counts in sorted(weekly.items())
    ]
    return GitHubContributions(
        schema_version=CONTRIBUTIONS_SCHEMA_VERSION,
        sample_start=sample_start,
        sample_end=sample_end,
        days_span=max(1, (sample_end - sample_start).days),
        total_events=len(events),
        push_events=push_events,
        pull_request_events=pull_request_events,
        distinct_repositories=len(distinct_repositories),
        open_source_repositories=sorted(open_source_repositories),
        open_source_events=open_source_events,
        weekly=weeks,
        rate_limit_remaining=rate_limit_remaining,
        rate_limit_reset=rate_limit_reset,
    )


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
                    repository_from_payload(repository) for repository in response.body
                )
                remaining = response.rate_limit_remaining
                reset = response.rate_limit_reset
                selected = select_repositories(repositories)
                if len(selected) == MAX_REPOSITORIES:
                    return selected, remaining, reset
                next_url = next_link(response.link)
                params = None

        return select_repositories(repositories), remaining, reset

    async def get_repository_inspections(
        self,
        repositories: list[GitHubRepository],
        username: str,
    ) -> tuple[list[RepositoryInspection], list[str], int | None, int | None]:
        inspections: list[RepositoryInspection] = []
        warnings: list[str] = []
        remaining: int | None = None
        reset: int | None = None

        async with self.client() as client:
            for repository in repositories:
                repository_path = quote(repository.full_name, safe="/")
                branch = quote(repository.default_branch, safe="")
                try:
                    tree_response = await self.get_json(
                        client,
                        f"/repos/{repository_path}/git/trees/{branch}",
                        username,
                        {"recursive": 1},
                    )
                except GitHubRateLimited as error:
                    reset = error.reset_at or reset
                    warnings.append(
                        f"{repository.full_name}: GitHub rate limit stopped file inspection"
                    )
                    break
                except (
                    GitHubTransientError,
                    GitHubUserNotFound,
                    httpx2.HTTPStatusError,
                ):
                    warnings.append(f"{repository.full_name}: file tree could not be inspected")
                    continue

                remaining = tree_response.rate_limit_remaining
                reset = tree_response.rate_limit_reset
                body = tree_response.body if isinstance(tree_response.body, dict) else {}
                tree = body.get("tree", [])
                if not isinstance(tree, list):
                    warnings.append(f"{repository.full_name}: invalid file tree response")
                    continue
                file_paths = sorted(
                    entry["path"]
                    for entry in tree[:MAX_TREE_ENTRIES]
                    if isinstance(entry, dict)
                    and entry.get("type") == "blob"
                    and isinstance(entry.get("path"), str)
                )
                truncated = bool(body.get("truncated")) or len(tree) > MAX_TREE_ENTRIES
                if truncated:
                    warnings.append(f"{repository.full_name}: file tree was truncated")

                manifest_paths = [
                    path
                    for path in file_paths
                    if PurePosixPath(path).name.lower() in MANIFEST_NAMES
                    and len(PurePosixPath(path).parts) <= 3
                ][:MAX_MANIFESTS_PER_REPOSITORY]
                dependencies: set[str] = set()
                loaded_manifests: list[str] = []
                for manifest_path in manifest_paths:
                    if remaining == 0:
                        warnings.append(
                            f"{repository.full_name}: GitHub rate limit stopped manifest inspection"
                        )
                        break
                    content_path = quote(manifest_path, safe="/")
                    try:
                        content_response = await self.get_json(
                            client,
                            f"/repos/{repository_path}/contents/{content_path}",
                            username,
                        )
                    except GitHubRateLimited as error:
                        remaining = 0
                        reset = error.reset_at or reset
                        warnings.append(
                            f"{repository.full_name}: GitHub rate limit stopped manifest inspection"
                        )
                        break
                    except (
                        GitHubTransientError,
                        GitHubUserNotFound,
                        httpx2.HTTPStatusError,
                    ):
                        warnings.append(
                            f"{repository.full_name}: {manifest_path} could not be inspected"
                        )
                        continue

                    remaining = content_response.rate_limit_remaining
                    reset = content_response.rate_limit_reset
                    content_body = (
                        content_response.body if isinstance(content_response.body, dict) else {}
                    )
                    encoded = content_body.get("content")
                    size = content_body.get("size")
                    if (
                        content_body.get("encoding") != "base64"
                        or not isinstance(encoded, str)
                        or not isinstance(size, int)
                        or size > MAX_MANIFEST_BYTES
                    ):
                        warnings.append(
                            f"{repository.full_name}: {manifest_path} content was unavailable"
                        )
                        continue
                    try:
                        content = base64.b64decode(encoded).decode()
                    except (binascii.Error, UnicodeDecodeError):
                        warnings.append(
                            f"{repository.full_name}: {manifest_path} content was invalid"
                        )
                        continue
                    dependencies.update(extract_dependencies(manifest_path, content))
                    loaded_manifests.append(manifest_path)

                inspections.append(
                    RepositoryInspection(
                        repository_full_name=repository.full_name,
                        default_branch=repository.default_branch,
                        file_paths=file_paths,
                        tree_truncated=truncated,
                        manifest_paths=loaded_manifests,
                        dependencies=sorted(dependencies),
                    )
                )
                if remaining == 0:
                    break
                try:
                    languages_response = await self.get_json(
                        client,
                        f"/repos/{repository_path}/languages",
                        username,
                    )
                except GitHubRateLimited as error:
                    remaining = 0
                    reset = error.reset_at or reset
                    warnings.append(
                        f"{repository.full_name}: GitHub rate limit stopped language data"
                    )
                    break
                except (
                    GitHubTransientError,
                    GitHubUserNotFound,
                    httpx2.HTTPStatusError,
                ):
                    warnings.append(f"{repository.full_name}: language data could not be inspected")
                    continue
                remaining = languages_response.rate_limit_remaining
                reset = languages_response.rate_limit_reset
                languages_body = languages_response.body
                if isinstance(languages_body, dict):
                    repository.languages = {
                        str(name): int(bytes_count)
                        for name, bytes_count in languages_body.items()
                        if isinstance(bytes_count, int)
                    }

        return inspections, warnings, remaining, reset

    async def get_contributions(
        self,
        username: str,
    ) -> GitHubContributions | None:
        """Aggregate recent public activity (commits, PRs, forks) for the user.

        Returns None when the user has no public event feed or events are
        unavailable, so contribution data never fails an analysis.
        """
        events: list[dict[str, Any]] = []
        remaining: int | None = None
        reset: int | None = None
        next_url: str | None = f"/users/{quote(username, safe='')}/events/public"
        params: dict[str, str | int] | None = {"per_page": 100}

        async with self.client() as client:
            for _ in range(MAX_EVENT_PAGES):
                if next_url is None or len(events) >= MAX_EVENTS:
                    break
                try:
                    response = await self.get_json(client, next_url, username, params)
                except (GitHubRateLimited, GitHubTransientError, GitHubUserNotFound):
                    break
                except httpx2.HTTPStatusError:
                    break
                body = response.body
                if not isinstance(body, list):
                    break
                events.extend(body)
                remaining = response.rate_limit_remaining
                reset = response.rate_limit_reset
                next_url = next_link(response.link)
                params = None

        if not events:
            return None
        return aggregate_contributions(events, username, remaining, reset)

    async def get_organizations(self, username: str) -> list[str]:
        """List public organization memberships; never fails an analysis."""
        try:
            async with self.client() as client:
                response = await self.get_json(
                    client,
                    f"/users/{quote(username, safe='')}/orgs",
                    username,
                    {"per_page": 100},
                )
        except (GitHubRateLimited, GitHubTransientError, GitHubUserNotFound):
            return []
        except httpx2.HTTPStatusError:
            return []
        body = response.body
        if not isinstance(body, list):
            return []
        return sorted(
            {
                organization["login"]
                for organization in body
                if isinstance(organization, dict) and isinstance(organization.get("login"), str)
            }
        )

    async def get_snapshot(self, username: str) -> GitHubSnapshot:
        snapshot = await self.get_profile(username)
        organizations = await self.get_organizations(username)
        try:
            repositories, remaining, reset = await self.get_repositories(username)
        except RepositoryCollectionFailed as error:
            raise GitHubPartialResult(
                GitHubSnapshot(
                    profile=snapshot.profile,
                    repositories=error.repositories,
                    contributions=await self.get_contributions(username),
                    organizations=organizations,
                    rate_limit_remaining=error.rate_limit_remaining
                    if error.rate_limit_remaining is not None
                    else snapshot.rate_limit_remaining,
                    rate_limit_reset=error.rate_limit_reset
                    if error.rate_limit_reset is not None
                    else snapshot.rate_limit_reset,
                ),
                error.warning,
            ) from error
        contributions = await self.get_contributions(username)
        (
            inspections,
            warnings,
            inspection_remaining,
            inspection_reset,
        ) = await self.get_repository_inspections(repositories, username)
        final_remaining = (
            inspection_remaining
            if inspection_remaining is not None
            else remaining
            if remaining is not None
            else snapshot.rate_limit_remaining
        )
        final_reset = (
            inspection_reset
            if inspection_reset is not None
            else reset
            if reset is not None
            else snapshot.rate_limit_reset
        )
        result = GitHubSnapshot(
            profile=snapshot.profile,
            repositories=repositories,
            inspections=inspections,
            contributions=contributions,
            organizations=organizations,
            rate_limit_remaining=final_remaining,
            rate_limit_reset=final_reset,
        )
        if warnings:
            raise GitHubPartialResult(result, summarize_warnings(warnings))
        return result
