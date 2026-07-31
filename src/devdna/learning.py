from dataclasses import dataclass

from devdna.schemas import LearningPlan, LearningRecommendation, ReportSnapshot

LEARNING_SCHEMA_VERSION = "1"
LEARNING_GENERATOR_VERSION = "python-backend-learning-v1"
MARKET_REVIEW_DATE = "2026-07-31"


@dataclass(frozen=True)
class LearningDetail:
    outcomes: tuple[str, ...]
    project_brief: str


ROLE_LEARNING: dict[str, LearningDetail] = {
    "python": LearningDetail(
        outcomes=(
            "Structure an installable Python application",
            "Manage and lock runtime dependencies",
            "Expose one documented application entry point",
        ),
        project_brief="Build a small typed Python service with repeatable local setup.",
    ),
    "api_framework": LearningDetail(
        outcomes=(
            "Design resource-oriented HTTP endpoints",
            "Validate request and response data",
            "Return stable client and server errors",
        ),
        project_brief=(
            "Publish a FastAPI service with validation, error handling, and OpenAPI docs."
        ),
    ),
    "testing": LearningDetail(
        outcomes=(
            "Separate unit and integration test boundaries",
            "Test one success and one failure path",
            "Run deterministic tests with one command",
        ),
        project_brief="Add pytest coverage around the service's highest-risk behavior.",
    ),
    "database": LearningDetail(
        outcomes=(
            "Model persistent domain data",
            "Apply reversible schema migrations",
            "Test transactions and constraint failures",
        ),
        project_brief="Add PostgreSQL persistence and a migration-backed workflow.",
    ),
    "automation": LearningDetail(
        outcomes=(
            "Run formatting, typing, and tests in CI",
            "Cache dependencies without hiding failures",
            "Protect the main branch with reproducible checks",
        ),
        project_brief="Create a GitHub Actions pipeline matching the documented local checks.",
    ),
    "delivery": LearningDetail(
        outcomes=(
            "Build a minimal non-root container image",
            "Configure services through environment variables",
            "Verify health and graceful shutdown behavior",
        ),
        project_brief=(
            "Containerize the service and its database with a health-checked Compose stack."
        ),
    ),
    "documentation": LearningDetail(
        outcomes=(
            "Explain the problem and architecture",
            "Document setup and verification commands",
            "Record one meaningful engineering tradeoff",
        ),
        project_brief="Rewrite the project README as a reproducible engineering handoff.",
    ),
}


def market_recommendation(priority: int) -> LearningRecommendation:
    return LearningRecommendation(
        priority=priority,
        kind="market_signal",
        title="Production AI service integration",
        rationale=(
            "GitHub's 2025 Octoverse data shows Python anchoring a large share of new AI "
            "projects, with growth shifting toward production packaging, orchestration, and "
            "deployment. Treat this as a dated market signal, not verified developer evidence."
        ),
        learning_outcomes=[
            "Wrap a model provider behind a typed service boundary",
            "Add timeouts, retries, cost limits, and safe error handling",
            "Evaluate output quality with deterministic test cases",
            "Instrument latency, failures, and model usage",
        ],
        project_brief=(
            "Extend a FastAPI project with one useful AI-backed endpoint, an evaluation fixture, "
            "failure controls, and operational telemetry."
        ),
        evidence_to_publish=[
            "Typed API route and provider adapter",
            "Evaluation and failure-path tests",
            "Security, privacy, and cost notes",
            "Container and run instructions",
        ],
        source_label="GitHub Octoverse 2025",
        source_url=(
            "https://github.blog/news-insights/octoverse/"
            "what-the-fastest-growing-tools-reveal-about-how-software-is-being-built/"
        ),
        reviewed_on=MARKET_REVIEW_DATE,
    )


def generate_learning_plan(report: ReportSnapshot) -> LearningPlan:
    recommendations: list[LearningRecommendation] = []
    for action in report.actions:
        detail = ROLE_LEARNING[action.requirement]
        recommendations.append(
            LearningRecommendation(
                priority=len(recommendations) + 1,
                kind="role_gap",
                title=action.title,
                rationale=action.rationale,
                learning_outcomes=list(detail.outcomes),
                project_brief=detail.project_brief,
                evidence_to_publish=list(action.evidence_needed),
            )
        )

    recommendations.append(market_recommendation(len(recommendations) + 1))
    return LearningPlan(
        schema_version=LEARNING_SCHEMA_VERSION,
        generator_version=LEARNING_GENERATOR_VERSION,
        target_role=report.target_role,
        recommendations=recommendations,
    )
