from dataclasses import dataclass


@dataclass(frozen=True)
class RubricRequirement:
    key: str
    title: str
    description: str
    evidence_keys: tuple[str, ...]
    action_title: str
    action_detail: str
    evidence_needed: tuple[str, ...]


@dataclass(frozen=True)
class RoleRubric:
    role: str
    version: str
    requirements: tuple[RubricRequirement, ...]


PYTHON_BACKEND_DEVELOPER = RoleRubric(
    role="python_backend_developer",
    version="python_backend_developer:v1",
    requirements=(
        RubricRequirement(
            key="python",
            title="Python project foundation",
            description="Python source code is paired with explicit dependency management.",
            evidence_keys=("python.project",),
            action_title="Publish a structured Python backend project",
            action_detail=(
                "Add a focused backend repository with installable dependencies and a clear "
                "application entry point."
            ),
            evidence_needed=("Python source files", "pyproject.toml or requirements.txt"),
        ),
        RubricRequirement(
            key="api_framework",
            title="Backend API framework",
            description="A recognized Python web framework is declared in project dependencies.",
            evidence_keys=(
                "api.framework.fastapi",
                "api.framework.django",
                "api.framework.flask",
            ),
            action_title="Expose a reviewable backend API",
            action_detail=(
                "Build a small HTTP API with FastAPI, Django, or Flask and document how to run it."
            ),
            evidence_needed=("Framework dependency", "API application source", "Run instructions"),
        ),
        RubricRequirement(
            key="testing",
            title="Automated testing",
            description="Python tests and a recognized pytest setup are present.",
            evidence_keys=("testing.pytest",),
            action_title="Add an automated test suite",
            action_detail=(
                "Cover core behavior and at least one failure path, then make the tests runnable "
                "with one documented command."
            ),
            evidence_needed=("tests/ or test_*.py", "pytest dependency or configuration"),
        ),
        RubricRequirement(
            key="database",
            title="Database engineering",
            description="Database libraries or migration tooling are declared.",
            evidence_keys=("database.tooling",),
            action_title="Demonstrate persistent data design",
            action_detail=(
                "Add a real database-backed workflow and commit schema migration configuration."
            ),
            evidence_needed=("Database dependency", "Schema or migration files"),
        ),
        RubricRequirement(
            key="automation",
            title="Continuous integration",
            description="A GitHub Actions workflow provides automated project checks.",
            evidence_keys=("automation.github_actions",),
            action_title="Run quality checks in CI",
            action_detail=(
                "Create a GitHub Actions workflow that installs dependencies and runs tests and "
                "static checks."
            ),
            evidence_needed=(".github/workflows/*.yml",),
        ),
        RubricRequirement(
            key="delivery",
            title="Containerized delivery",
            description="Container build or orchestration configuration is present.",
            evidence_keys=("delivery.container",),
            action_title="Make the project reproducible with containers",
            action_detail=(
                "Add a production-focused Dockerfile or Compose setup with documented startup."
            ),
            evidence_needed=("Dockerfile or Compose configuration",),
        ),
        RubricRequirement(
            key="documentation",
            title="Project documentation",
            description="Repository documentation explains the project.",
            evidence_keys=("documentation.project",),
            action_title="Document the engineering story",
            action_detail=(
                "Explain the problem, architecture, setup, verification commands, and key "
                "tradeoffs."
            ),
            evidence_needed=("README or docs/ content",),
        ),
    ),
)

RUBRICS = {PYTHON_BACKEND_DEVELOPER.role: PYTHON_BACKEND_DEVELOPER}


def get_rubric(role: str) -> RoleRubric:
    try:
        return RUBRICS[role]
    except KeyError as error:
        raise ValueError(f"unsupported role: {role}") from error
