"""Deterministic deep-search insights for a developer's recent work.

Commit intelligence comes from real repository commits fetched directly from
the GitHub API (`/repos/{repo}/commits?author=user`) because the public event
feed often omits push payloads. Event-derived signals (merged PRs, opened
issues, open-source share) come from the already-downloaded event list — no
vanity metrics anywhere.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from devdna.schemas import ActivityInsights, MergedPullRequest, NotableCommit

ACTIVITY_SCHEMA_VERSION = "1"

MAX_NOTABLE_COMMITS = 8
MAX_MERGED_PULL_REQUESTS = 6
MAX_MESSAGE_LENGTH = 140
MAX_REPOSITORIES = 12

COMMIT_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("feature", re.compile(r"^\s*(?:feat|feature)\b", re.IGNORECASE)),
    ("fix", re.compile(r"^\s*(?:fix|bugfix|hotfix|patch)\b", re.IGNORECASE)),
    ("performance", re.compile(r"^\s*perf\b", re.IGNORECASE)),
    ("refactor", re.compile(r"^\s*(?:refactor|clean\s*up|cleanup)\b", re.IGNORECASE)),
    ("tests", re.compile(r"^\s*(?:test|spec)\b", re.IGNORECASE)),
    ("docs", re.compile(r"^\s*(?:doc|docs|readme)\b", re.IGNORECASE)),
)

NOISE_PATTERN = re.compile(
    r"""
    ^\s*
    (?:
        merge\b
        | revert\b
        | wip\b
        | tmp\b
        | temp\b
        | misc\b
        | asdf+
        | chore\b
        | update\s+dependencies\b
        | bump\s+\S+\s+from\s+\S+\s+to\s+\S+
        | initial\s+commit$
        | first\s+commit$
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

BOT_PATTERN = re.compile(
    r"\[(?:bot|skip ci|ci skip|no ci)\]|\b(?:dependabot|renovate)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class CommitEntry:
    """One real commit fetched from a repository's commit list."""

    message: str
    repository: str
    url: str | None
    occurred_at: datetime


def _parse_event_time(event: Mapping[str, Any]) -> datetime | None:
    created = event.get("created_at")
    if not isinstance(created, str):
        return None
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return None


def _repo_name(event: Mapping[str, Any]) -> str | None:
    repo = event.get("repo")
    name = repo.get("name") if isinstance(repo, dict) else None
    if isinstance(name, str) and "/" in name:
        return name
    return None


def classify_commit(message: str) -> tuple[str, bool]:
    """Return (kind, is_meaningful) for a commit message first line."""
    for kind, pattern in COMMIT_KIND_PATTERNS:
        if pattern.search(message):
            return kind, True
    stripped = message.strip()
    if NOISE_PATTERN.match(stripped) or BOT_PATTERN.search(stripped):
        return "noise", False
    if len(stripped) >= 40:
        return "general", True
    if len(stripped) >= 25 and " " in stripped:
        return "general", True
    return "noise", False


def extract_activity_insights(
    events: list[dict[str, Any]],
    username: str,
    commit_entries: list[CommitEntry] | None = None,
) -> ActivityInsights | None:
    """Build insights from raw events plus optional directly-fetched commits.

    When ``commit_entries`` is provided it is the authoritative commit source;
    push-event payloads are ignored because the public events feed often strips
    them. Event data still supplies merged PRs, issue counts, and OSS share.
    """
    commits_analyzed = 0
    meaningful = 0
    features = fixes = tests_docs = refactors = 0
    opened_pull_requests = 0
    issues_opened = 0
    open_source_events = 0
    total_events = 0
    repositories: dict[str, None] = {}
    notable: list[NotableCommit] = []
    merged_prs: list[MergedPullRequest] = []
    sample_times: list[datetime] = []

    classified_commits: list[tuple[str, NotableCommit]] = []
    if commit_entries is not None:
        for entry in commit_entries:
            first_line = entry.message.strip().splitlines()[0][:MAX_MESSAGE_LENGTH]
            kind, is_meaningful = classify_commit(first_line)
            commits_analyzed += 1
            if not is_meaningful:
                continue
            classified_commits.append(
                (
                    kind,
                    NotableCommit(
                        message=first_line,
                        repository=entry.repository,
                        url=entry.url,
                        occurred_at=entry.occurred_at,
                        kind=kind,
                    ),
                )
            )
        notable = [item for _, item in classified_commits]

    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        occurred = _parse_event_time(event)
        repo_name = _repo_name(event)
        if repo_name is None or occurred is None:
            continue
        total_events += 1
        sample_times.append(occurred)
        owner = repo_name.split("/", 1)[0]
        is_open_source = owner.lower() != username.lower()
        if is_open_source:
            open_source_events += 1
        if len(repositories) < MAX_REPOSITORIES or repo_name in repositories:
            repositories.setdefault(repo_name, None)

        raw_payload = event.get("payload")
        payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}

        if event_type == "PushEvent" and commit_entries is None:
            commits = payload.get("commits")
            if isinstance(commits, list):
                for commit in commits:
                    if not isinstance(commit, dict):
                        continue
                    raw_message = commit.get("message")
                    if not isinstance(raw_message, str):
                        continue
                    first_line = raw_message.strip().splitlines()[0][:MAX_MESSAGE_LENGTH]
                    commits_analyzed += 1
                    kind, is_meaningful = classify_commit(first_line)
                    if not is_meaningful:
                        continue
                    classified_commits.append(
                        (
                            kind,
                            NotableCommit(
                                message=first_line,
                                repository=repo_name,
                                url=f"https://github.com/{repo_name}/commit/{commit.get('sha')}"
                                if isinstance(commit.get("sha"), str)
                                else None,
                                occurred_at=occurred,
                                kind=kind,
                            ),
                        )
                    )

        elif event_type == "PullRequestEvent":
            action = payload.get("action")
            raw_pull_request = payload.get("pull_request")
            pull_request: dict[str, Any] = (
                raw_pull_request if isinstance(raw_pull_request, dict) else {}
            )
            title = pull_request.get("title")
            html_url = pull_request.get("html_url")
            if action == "opened":
                opened_pull_requests += 1
            if action == "closed" and pull_request.get("merged") is True:
                merged_prs.append(
                    MergedPullRequest(
                        title=str(title)[:MAX_MESSAGE_LENGTH] if isinstance(title, str) else "",
                        repository=repo_name,
                        url=str(html_url) if isinstance(html_url, str) else None,
                        occurred_at=occurred,
                    )
                )

        elif event_type == "IssuesEvent":
            if payload.get("action") == "opened":
                issues_opened += 1

    for kind, _ in classified_commits:
        meaningful += 1
        if kind == "feature":
            features += 1
        elif kind == "fix":
            fixes += 1
        elif kind in {"tests", "docs"}:
            tests_docs += 1
        elif kind in {"refactor", "performance"}:
            refactors += 1

    notable = [item for _, item in classified_commits]
    notable.sort(key=lambda commit: commit.occurred_at, reverse=True)
    merged_prs.sort(key=lambda item: item.occurred_at, reverse=True)

    if commit_entries is not None:
        entry_times = [entry.occurred_at for entry in commit_entries]
        event_times = [t for t in sample_times]
        all_times = [t for t in [*entry_times, *event_times] if t is not None]
        sample_start = min(all_times) if all_times else None
        sample_end = max(all_times) if all_times else None
    else:
        if total_events == 0:
            return None
        sample_start = min(sample_times) if sample_times else None
        sample_end = max(sample_times) if sample_times else None

    return ActivityInsights(
        schema_version=ACTIVITY_SCHEMA_VERSION,
        sample_start=sample_start,
        sample_end=sample_end,
        commits_analyzed=commits_analyzed,
        meaningful_commits=meaningful,
        features_shipped=features,
        fixes_landed=fixes,
        tests_and_docs=tests_docs,
        refactors=refactors,
        merged_pull_requests=merged_prs[:MAX_MERGED_PULL_REQUESTS],
        opened_pull_requests=opened_pull_requests,
        issues_opened=issues_opened,
        repositories_touched=list(repositories)[:MAX_REPOSITORIES],
        open_source_share=round(open_source_events * 100 / total_events) if total_events else 0,
        notable_commits=notable[:MAX_NOTABLE_COMMITS],
    )


def activity_window_label(insights: ActivityInsights) -> str:
    """Human window label from the actual event sample."""
    if insights.sample_start is None or insights.sample_end is None:
        return "recent public activity"
    days = max(1, (insights.sample_end - insights.sample_start).days + 1)
    if days <= 1:
        return "last 24 hours"
    if days <= 31:
        return f"last {days} days"
    return f"last {days} days (~{days // 30} months)"
