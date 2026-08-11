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

FRONTEND_DEVELOPER = RoleRubric(
    role="frontend_developer",
    version="frontend_developer:v1",
    requirements=(
        RubricRequirement(
            key="frontend.app",
            title="Frontend application source",
            description="JavaScript or TypeScript source pairs with an npm dependency manifest.",
            evidence_keys=("frontend.app",),
            action_title="Publish a structured frontend application",
            action_detail=(
                "Add a focused frontend repository with installable dependencies and a clear "
                "application entry point."
            ),
            evidence_needed=("Source files", "package.json"),
        ),
        RubricRequirement(
            key="frontend.framework",
            title="Component framework",
            description="A recognized web framework is declared in project dependencies.",
            evidence_keys=(
                "frontend.framework.react",
                "frontend.framework.vue",
                "frontend.framework.svelte",
                "frontend.framework.angular",
            ),
            action_title="Build with a component framework",
            action_detail=(
                "Create a small interactive UI with React, Vue, Svelte, or Angular and document "
                "how to run it."
            ),
            evidence_needed=("Framework dependency", "Component source", "Run instructions"),
        ),
        RubricRequirement(
            key="frontend.testing",
            title="Frontend automated testing",
            description="A frontend test runner and testing-library setup are present.",
            evidence_keys=("frontend.testing",),
            action_title="Add a frontend test suite",
            action_detail=(
                "Cover component behavior and at least one interaction path, then make the tests "
                "runnable with one documented command."
            ),
            evidence_needed=("Test files", "Vitest/Jest dependency or configuration"),
        ),
        RubricRequirement(
            key="frontend.styling",
            title="Styling system",
            description="A styling approach is declared or visible in source.",
            evidence_keys=("frontend.styling",),
            action_title="Establish a consistent styling system",
            action_detail=(
                "Add CSS modules, Sass, or a utility framework with themed, reusable styles."
            ),
            evidence_needed=("Style files", "Styling dependency"),
        ),
        RubricRequirement(
            key="frontend.typescript",
            title="Type-safe frontend",
            description="TypeScript is configured and used in the application.",
            evidence_keys=("frontend.typescript",),
            action_title="Adopt TypeScript",
            action_detail=("Add a tsconfig.json and type the core data flow of the application."),
            evidence_needed=("tsconfig.json", "TypeScript source files"),
        ),
        RubricRequirement(
            key="automation.github_actions",
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
            key="delivery.container",
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
            key="documentation.project",
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

DEVOPS_ENGINEER = RoleRubric(
    role="devops_engineer",
    version="devops_engineer:v1",
    requirements=(
        RubricRequirement(
            key="infrastructure.container",
            title="Container packaging",
            description="Container build or orchestration configuration is present.",
            evidence_keys=("delivery.container",),
            action_title="Package applications as containers",
            action_detail=(
                "Add a production-focused Dockerfile or Compose setup with documented startup."
            ),
            evidence_needed=("Dockerfile or Compose configuration",),
        ),
        RubricRequirement(
            key="infrastructure.ci",
            title="Continuous integration",
            description="A GitHub Actions workflow provides automated checks.",
            evidence_keys=("automation.github_actions",),
            action_title="Automate checks in CI",
            action_detail=(
                "Create a GitHub Actions workflow that installs dependencies and runs tests and "
                "static checks."
            ),
            evidence_needed=(".github/workflows/*.yml",),
        ),
        RubricRequirement(
            key="infrastructure.as_code",
            title="Infrastructure as code",
            description="Infrastructure provisioning or configuration files are present.",
            evidence_keys=("infrastructure.as_code",),
            action_title="Manage infrastructure as code",
            action_detail=(
                "Add Terraform, CloudFormation, Ansible, or Kubernetes manifests that describe "
                "reproducible infrastructure."
            ),
            evidence_needed=("Infrastructure manifest", "Apply or plan documentation"),
        ),
        RubricRequirement(
            key="infrastructure.observability",
            title="Observability configuration",
            description="Logging, metrics, or tracing configuration is present.",
            evidence_keys=("infrastructure.observability",),
            action_title="Add observable signals",
            action_detail=(
                "Expose structured logs, metrics, or tracing from the application or its runtime."
            ),
            evidence_needed=("Observability config", "Log or metric exporter source"),
        ),
        RubricRequirement(
            key="infrastructure.secrets",
            title="Secret management",
            description="Secret handling avoids hard-coded credentials.",
            evidence_keys=("infrastructure.secrets",),
            action_title="Manage secrets safely",
            action_detail=(
                "Reference secrets through environment variables or a secret manager and commit "
                "only example values."
            ),
            evidence_needed=("Secret manager reference", ".env.example or equivalent"),
        ),
        RubricRequirement(
            key="infrastructure.servicing",
            title="Deployment configuration",
            description="A service or deployment definition documents how the system runs.",
            evidence_keys=("infrastructure.servicing",),
            action_title="Document a repeatable deployment",
            action_detail=(
                "Add a service, deployment, or platform configuration with clear run steps."
            ),
            evidence_needed=("Deployment config", "Run and rollback steps"),
        ),
        RubricRequirement(
            key="documentation.project",
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

RUBRICS = {
    PYTHON_BACKEND_DEVELOPER.role: PYTHON_BACKEND_DEVELOPER,
    FRONTEND_DEVELOPER.role: FRONTEND_DEVELOPER,
    DEVOPS_ENGINEER.role: DEVOPS_ENGINEER,
}

ROLE_LABELS = {
    "python_backend_developer": "Python backend developer",
    "frontend_developer": "Frontend developer",
    "devops_engineer": "DevOps engineer",
}


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def supported_roles() -> list[str]:
    return list(RUBRICS.keys())


def get_rubric(role: str) -> RoleRubric:
    try:
        return RUBRICS[role]
    except KeyError as error:
        raise ValueError(f"unsupported role: {role}") from error
