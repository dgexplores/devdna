import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
AnalysisStatus = Literal["queued", "running", "completed", "partial", "failed"]


class AnalysisCreate(BaseModel):
    github_username: str
    target_role: Literal["python_backend_developer"]

    @field_validator("github_username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value) or "--" in value:
            raise ValueError("invalid GitHub username")
        return value.lower()


class AnalysisResponse(BaseModel):
    id: str
    github_username: str
    target_role: str
    status: AnalysisStatus
    profile_snapshot: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GitHubProfile(BaseModel):
    login: str
    id: int
    avatar_url: str
    html_url: str
    name: str | None = None
    company: str | None = None
    blog: str | None = None
    location: str | None = None
    bio: str | None = None
    public_repos: int
    followers: int
    following: int
    created_at: datetime
    updated_at: datetime


class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    html_url: str
    description: str | None = None
    fork: bool
    archived: bool
    disabled: bool
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    size: int
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    default_branch: str
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None = None


class GitHubSnapshot(BaseModel):
    profile: GitHubProfile
    repositories: list[GitHubRepository] = Field(default_factory=list)
    rate_limit_remaining: int | None
    rate_limit_reset: int | None
