import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
AnalysisStatus = Literal["queued", "running", "completed", "partial", "failed"]
SupportedRole = Literal[
    "python_backend_developer",
    "frontend_react_developer",
    "frontend_developer",
    "devops_engineer",
]


class AnalysisCreate(BaseModel):
    github_username: str
    target_role: SupportedRole = "python_backend_developer"

    @field_validator("github_username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value) or "--" in value:
            raise ValueError("invalid GitHub username")
        return value.lower()


class JdAlignmentCreate(BaseModel):
    jd_text: str = Field(min_length=1, max_length=200_000)


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
    license_name: str | None = None
    topics: list[str] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)
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


class ContributionWeek(BaseModel):
    week_start: str
    push_count: int
    pull_request_count: int


class GitHubContributions(BaseModel):
    schema_version: str
    sample_start: datetime
    sample_end: datetime
    days_span: int
    total_events: int
    push_events: int
    pull_request_events: int
    distinct_repositories: int
    open_source_repositories: list[str] = Field(default_factory=list)
    open_source_events: int
    weekly: list[ContributionWeek] = Field(default_factory=list)
    rate_limit_remaining: int | None = None
    rate_limit_reset: int | None = None


class NotableCommit(BaseModel):
    message: str
    repository: str
    url: str | None = None
    occurred_at: datetime
    kind: str


class MergedPullRequest(BaseModel):
    title: str
    repository: str
    url: str | None = None
    occurred_at: datetime


class ActivityInsights(BaseModel):
    schema_version: str = "1"
    sample_start: datetime | None = None
    sample_end: datetime | None = None
    commits_analyzed: int = 0
    meaningful_commits: int = 0
    features_shipped: int = 0
    fixes_landed: int = 0
    tests_and_docs: int = 0
    refactors: int = 0
    merged_pull_requests: list[MergedPullRequest] = Field(default_factory=list)
    opened_pull_requests: int = 0
    issues_opened: int = 0
    repositories_touched: list[str] = Field(default_factory=list)
    open_source_share: int = 0
    notable_commits: list[NotableCommit] = Field(default_factory=list)


class GitHubSnapshot(BaseModel):
    profile: GitHubProfile
    repositories: list[GitHubRepository] = Field(default_factory=list)
    inspections: list[RepositoryInspection] = Field(default_factory=list)
    contributions: GitHubContributions | None = None
    activity: ActivityInsights | None = None
    organizations: list[str] = Field(default_factory=list)
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
    technologies: list[str] = Field(default_factory=list)
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
    solution: str | None = None
    template: str | None = None


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
    tech_stack: list[str] = Field(default_factory=list)
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
    style: str = "minimal"
    repositories: list[ReadmeRepository] = Field(default_factory=list)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    markdown: str


class LearningRecommendation(BaseModel):
    priority: int
    kind: Literal["role_gap", "market_signal"]
    title: str
    rationale: str
    learning_outcomes: list[str]
    project_brief: str
    evidence_to_publish: list[str]
    source_label: str | None = None
    source_url: str | None = None
    reviewed_on: str | None = None


class LearningPlan(BaseModel):
    schema_version: str
    generator_version: str
    target_role: str
    recommendations: list[LearningRecommendation]


class RecruiterCandidateResult(BaseModel):
    rank: int | None
    analysis_id: str
    github_username: str
    status: AnalysisStatus
    requirements_met: int | None = None
    requirements_total: int | None = None
    alignment_label: str | None = None
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    capability_highlights: list[str] = Field(default_factory=list)


class RecruiterBatchResponse(BaseModel):
    id: str
    target_role: str
    source_filename: str
    created_at: datetime
    candidates: list[RecruiterCandidateResult]


class CvSkillAlignment(BaseModel):
    skill: str
    status: Literal["verified", "self_reported_unverified"]
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)


class CvAlignment(BaseModel):
    schema_version: str
    analyzer_version: str
    github_username: str
    source_filename: str
    skills: list[CvSkillAlignment]
    suggested_summary: str
    guidance: list[str]


class JdSkillMatch(BaseModel):
    skill: str
    mentions: int
    status: Literal["verified", "unverified"]
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)


class JdAlignment(BaseModel):
    schema_version: str
    analyzer_version: str
    github_username: str
    requirements_considered: int
    skills: list[JdSkillMatch]
    verified_count: int
    missing_skills: list[str]
    suggested_summary: str
    guidance: list[str]
