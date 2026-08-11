from datetime import UTC, datetime

import pytest

from devdna.reports import generate_report
from devdna.schemas import (
    ContributionWeek,
    EvidenceItem,
    EvidenceSnapshot,
    EvidenceSource,
    GitHubContributions,
    GitHubProfile,
)
from devdna.web import render_report_page


def evidence_snapshot() -> EvidenceSnapshot:
    return EvidenceSnapshot(
        schema_version="1",
        analyzer_version="python-backend-evidence-v1",
        target_role="python_backend_developer",
        rubric_version="python_backend_developer:v1",
        repositories_analyzed=1,
        items=[
            EvidenceItem(
                key="python.project",
                category="language",
                claim="Python source and a manifest are present.",
                repository="octocat/backend",
                sources=[
                    EvidenceSource(
                        repository="octocat/backend",
                        path="src/main.py",
                        url="https://github.com/octocat/backend/blob/main/src/main.py",
                    ),
                    EvidenceSource(
                        repository="octocat/backend",
                        path="pyproject.toml",
                        url="https://github.com/octocat/backend/blob/main/pyproject.toml",
                    ),
                ],
            ),
            EvidenceItem(
                key="documentation.project",
                category="documentation",
                claim="Documentation is present.",
                repository="octocat/backend",
                sources=[
                    EvidenceSource(
                        repository="octocat/backend",
                        path="README.md",
                        url="https://github.com/octocat/backend/blob/main/README.md",
                    )
                ],
            ),
        ],
    )


def test_generate_report_maps_evidence_to_strengths_gaps_and_actions() -> None:
    report = generate_report(evidence_snapshot(), "completed")

    assert report.report_version == "python-backend-report-v1"
    assert report.alignment_label == "Foundational role alignment"
    assert report.requirements_met == 2
    assert report.requirements_total == 7
    assert [strength.requirement for strength in report.strengths] == [
        "python",
        "documentation",
    ]
    assert [gap.requirement for gap in report.gaps] == [
        "api_framework",
        "testing",
        "database",
        "automation",
        "delivery",
    ]
    assert [action.priority for action in report.actions] == [1, 2, 3, 4, 5]
    assert report.strengths[0].sources[0].path == "pyproject.toml"


def test_generate_partial_report_does_not_present_missing_data_as_absence() -> None:
    report = generate_report(
        evidence_snapshot(),
        "partial",
        "octocat/backend: file tree was truncated",
    )

    assert report.collection_status == "partial"
    assert report.warning == "octocat/backend: file tree was truncated"
    assert all(
        "not verified in the available inspection data" in gap.explanation for gap in report.gaps
    )


def test_generate_report_rejects_mismatched_rubric() -> None:
    evidence = evidence_snapshot().model_copy(
        update={"rubric_version": "python_backend_developer:v0"}
    )

    with pytest.raises(ValueError, match="does not match"):
        generate_report(evidence, "completed")


def test_render_report_page_escapes_source_paths_and_exposes_evidence() -> None:
    report = generate_report(evidence_snapshot(), "completed")
    report.strengths[0].sources[0].path = "<script>alert(1)</script>"

    html = render_report_page("octocat", "analysis-id", report)

    assert "The evidence spine" in html
    assert "Build next" in html
    assert 'aria-label="Rubric coverage"' in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "/v1/analyses/analysis-id/report" in html


def test_render_report_page_without_contributions_does_not_500() -> None:
    report = generate_report(evidence_snapshot(), "completed")
    profile = GitHubProfile(
        login="octocat",
        id=1,
        avatar_url="https://example.com/avatar.png",
        html_url="https://github.com/octocat",
        name=None,
        public_repos=5,
        followers=10,
        following=3,
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    html = render_report_page(
        "octocat",
        "analysis-id",
        report,
        profile=profile,
        contributions=None,
    )

    assert "Profile overview" in html
    assert "Contribution frequency" not in html


def test_render_report_page_with_empty_open_source_repos_does_not_500() -> None:
    report = generate_report(evidence_snapshot(), "completed")
    profile = GitHubProfile(
        login="octocat",
        id=1,
        avatar_url="https://example.com/avatar.png",
        html_url="https://github.com/octocat",
        name=None,
        public_repos=5,
        followers=10,
        following=3,
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    contributions = GitHubContributions(
        schema_version="1",
        sample_start=datetime(2026, 7, 1, tzinfo=UTC),
        sample_end=datetime(2026, 7, 8, tzinfo=UTC),
        days_span=7,
        total_events=0,
        push_events=0,
        pull_request_events=0,
        distinct_repositories=0,
        open_source_events=0,
        open_source_repositories=[],
        weekly=[ContributionWeek(week_start="2026-07-01", push_count=0, pull_request_count=0)],
    )

    html = render_report_page(
        "octocat",
        "analysis-id",
        report,
        profile=profile,
        contributions=contributions,
    )

    assert "Profile overview" in html
    assert "Open-source activity" not in html
