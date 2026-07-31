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
    evidence_snapshot: dict[str, Any] | None
    report_snapshot: dict[str, Any] | None
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


class RepositoryInspection(BaseModel):
    repository_full_name: str
    default_branch: str
    file_paths: list[str] = Field(default_factory=list)
    tree_truncated: bool = False
    manifest_paths: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class GitHubSnapshot(BaseModel):
    profile: GitHubProfile
    repositories: list[GitHubRepository] = Field(default_factory=list)
    inspections: list[RepositoryInspection] = Field(default_factory=list)
    rate_limit_remaining: int | None
    rate_limit_reset: int | None


class EvidenceSource(BaseModel):
    repository: str
    path: str
    url: str


class EvidenceItem(BaseModel):
    key: str
    category: str
    claim: str
    repository: str
    sources: list[EvidenceSource]


class EvidenceSnapshot(BaseModel):
    schema_version: str
    analyzer_version: str
    target_role: str
    rubric_version: str
    repositories_analyzed: int
    items: list[EvidenceItem] = Field(default_factory=list)


class ReportStrength(BaseModel):
    requirement: str
    title: str
    summary: str
    repositories: list[str]
    sources: list[EvidenceSource]


class ReportGap(BaseModel):
    requirement: str
    title: str
    explanation: str


class ReportAction(BaseModel):
    priority: int
    requirement: str
    title: str
    rationale: str
    evidence_needed: list[str]


class ReportSnapshot(BaseModel):
    schema_version: str
    report_version: str
    analyzer_version: str
    rubric_version: str
    target_role: str
    collection_status: Literal["completed", "partial"]
    warning: str | None = None
    alignment_label: str
    requirements_met: int
    requirements_total: int
    strengths: list[ReportStrength] = Field(default_factory=list)
    gaps: list[ReportGap] = Field(default_factory=list)
    actions: list[ReportAction] = Field(default_factory=list)


class ReadmeRepository(BaseModel):
    name: str
    url: str
    evidence: list[str]


class ReadmeDraft(BaseModel):
    schema_version: str
    generator_version: str
    github_username: str
    repositories: list[ReadmeRepository] = Field(default_factory=list)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    markdown: str
