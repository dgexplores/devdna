from dataclasses import dataclass

from devdna.schemas import LearningPlan, LearningRecommendation, ReportSnapshot

LEARNING_SCHEMA_VERSION = "1"
LEARNING_GENERATOR_VERSION = "python-backend-learning-v1"
LEARNING_GENERATOR_VERSIONS = {
    "python_backend_developer": "python-backend-learning-v1",
    "frontend_react_developer": "frontend-react-learning-v1",
    "frontend_developer": "frontend-learning-v1",
    "devops_engineer": "devops-learning-v1",
}
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
    "react.app": LearningDetail(
        outcomes=(
            "Scaffold an installable React application",
            "Declare and lock npm runtime dependencies",
            "Expose one documented application entry point",
        ),
        project_brief="Build a small typed React application with repeatable local setup.",
    ),
    "react.framework": LearningDetail(
        outcomes=(
            "Compose reusable React components",
            "Manage component state and user interactions",
            "Separate presentational and data-fetching boundaries",
        ),
        project_brief="Publish a React component that renders state and handles a user action.",
    ),
    "react.testing": LearningDetail(
        outcomes=(
            "Separate unit and interaction test boundaries",
            "Test one render and one interaction path",
            "Run deterministic frontend tests with one command",
        ),
        project_brief=(
            "Add Vitest or Jest with Testing Library around the app's highest-risk behavior."
        ),
    ),
    "react.styling": LearningDetail(
        outcomes=(
            "Build reusable, themed components",
            "Use a consistent spacing and token system",
            "Keep styles scoped to components",
        ),
        project_brief=(
            "Add CSS modules, Sass, Tailwind, or styled-components with themed components."
        ),
    ),
    "react.typescript": LearningDetail(
        outcomes=(
            "Configure a strict TypeScript compiler",
            "Type props, state, and API payloads",
            "Run type checking in the local verify command",
        ),
        project_brief="Convert the core React data flow to typed TypeScript modules.",
    ),
    "automation.github_actions": LearningDetail(
        outcomes=(
            "Run lint, type checks, and tests in CI",
            "Cache npm dependencies without hiding failures",
            "Protect the main branch with reproducible checks",
        ),
        project_brief="Create a GitHub Actions pipeline matching the documented local checks.",
    ),
    "delivery.container": LearningDetail(
        outcomes=(
            "Build static assets in a multi-stage image",
            "Serve the build from a non-root user",
            "Verify health and graceful shutdown behavior",
        ),
        project_brief="Containerize the frontend build and serve it from a health-checked image.",
    ),
    "documentation.project": LearningDetail(
        outcomes=(
            "Explain the problem and architecture",
            "Document setup and verification commands",
            "Record one meaningful engineering tradeoff",
        ),
        project_brief="Rewrite the project README as a reproducible engineering handoff.",
    ),
}


def market_recommendation(priority: int, role: str) -> LearningRecommendation:
    if role == "frontend_react_developer":
        return LearningRecommendation(
            priority=priority,
            kind="market_signal",
            title="Production React application engineering",
            rationale=(
                "GitHub's 2025 Octoverse data shows JavaScript and TypeScript anchoring a large "
                "share of new projects, with frontend work shifting toward build performance, "
                "type safety, and production delivery. Treat this as a dated market signal, not "
                "verified developer evidence."
            ),
            learning_outcomes=[
                "Optimize bundle size and initial render performance",
                "Type shared state and API contracts end to end",
                "Add monitoring, error boundaries, and accessibility checks",
                "Ship with reproducible builds and automated deployment",
            ],
            project_brief=(
                "Extend a React project with one production-oriented feature: typed API "
                "integration, performance instrumentation, and a reproducible build pipeline."
            ),
            evidence_to_publish=[
                "Typed React components and API contracts",
                "Interaction and accessibility tests",
                "Performance and error-handling notes",
                "Build and run instructions",
            ],
            source_label="GitHub Octoverse 2025",
            source_url=(
                "https://github.blog/news-insights/octoverse/"
                "what-the-fastest-growing-tools-reveal-about-how-software-is-being-built/"
            ),
            reviewed_on=MARKET_REVIEW_DATE,
        )
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


def learning_generator_version(role: str) -> str:
    return LEARNING_GENERATOR_VERSIONS.get(role, LEARNING_GENERATOR_VERSION)


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

    recommendations.append(market_recommendation(len(recommendations) + 1, report.target_role))
    return LearningPlan(
        schema_version=LEARNING_SCHEMA_VERSION,
        generator_version=learning_generator_version(report.target_role),
        target_role=report.target_role,
        recommendations=recommendations,
    )
