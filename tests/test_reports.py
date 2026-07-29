import pytest

from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource
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
    assert "What strengthens the profile next" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "/v1/analyses/analysis-id/report" in html
