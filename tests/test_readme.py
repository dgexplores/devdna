from devdna.readme import generate_profile_readme
from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource


def report_with_python_evidence() -> EvidenceSnapshot:
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
                        path="pyproject.toml",
                        url="https://github.com/octocat/backend/blob/main/pyproject.toml",
                    )
                ],
            )
        ],
    )


def test_readme_draft_uses_only_report_strengths_and_sources() -> None:
    report = generate_report(report_with_python_evidence(), "completed")

    draft = generate_profile_readme("octocat", report)

    assert draft.generator_version == "evidence-readme-v1"
    assert draft.repositories[0].name == "octocat/backend"
    assert draft.evidence_sources[0].path == "pyproject.toml"
    assert "[octocat/backend](https://github.com/octocat/backend)" in draft.markdown
    assert "[Python project foundation]" in draft.markdown
    assert (
        "Automated testing"
        not in draft.markdown.split("## Engineering evidence")[1].split(
            "## Currently strengthening"
        )[0]
    )


def test_readme_without_strengths_uses_aspirational_language() -> None:
    evidence = report_with_python_evidence().model_copy(update={"items": []})
    report = generate_report(evidence, "completed")

    draft = generate_profile_readme("octocat", report)

    assert "Building toward Python backend development" in draft.markdown
    assert "## Engineering evidence" not in draft.markdown
    assert "## Currently strengthening" in draft.markdown
