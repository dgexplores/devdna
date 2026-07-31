from devdna.learning import MARKET_REVIEW_DATE, generate_learning_plan
from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource


def evidence_with_python() -> EvidenceSnapshot:
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
                claim="Python source and dependency management are present.",
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


def test_learning_plan_orders_role_gaps_before_dated_market_signal() -> None:
    report = generate_report(evidence_with_python(), "completed")

    plan = generate_learning_plan(report)

    assert plan.recommendations[0].kind == "role_gap"
    assert plan.recommendations[0].title == "Expose a reviewable backend API"
    assert plan.recommendations[0].learning_outcomes
    assert plan.recommendations[-1].kind == "market_signal"
    assert plan.recommendations[-1].reviewed_on == MARKET_REVIEW_DATE
    assert plan.recommendations[-1].source_label == "GitHub Octoverse 2025"
    assert [item.priority for item in plan.recommendations] == list(
        range(1, len(plan.recommendations) + 1)
    )


def test_learning_plan_does_not_recommend_verified_requirement_as_gap() -> None:
    report = generate_report(evidence_with_python(), "completed")

    plan = generate_learning_plan(report)

    role_titles = [item.title for item in plan.recommendations if item.kind == "role_gap"]
    assert "Publish a structured Python backend project" not in role_titles
    assert "Add an automated test suite" in role_titles
