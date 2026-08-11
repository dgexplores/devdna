from dataclasses import dataclass

PYTHON_PROJECT_TEMPLATE = """# pyproject.toml
[project]
name = "my-service"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.116",
  "sqlalchemy>=2.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]"""

FASTAPI_APP_TEMPLATE = """# app/main.py
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}"""

PYTEST_TEMPLATE = """# pytest.ini
[pytest]
testpaths = tests

# tests/test_app.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200"""

DATABASE_TEMPLATE = """# 1. Initialize migrations
alembic init migrations

# 2. Declare a model (models.py)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)

# 3. Generate and apply
alembic revision --autogenerate -m "create items table"
alembic upgrade head"""

CI_TEMPLATE = """# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest"""

DOCKERFILE_TEMPLATE = """# Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD ["python", "-m", "app"]"""

README_TEMPLATE = """# Project name

One sentence: what problem this project solves.

## Setup
```bash
pip install -r requirements.txt
python -m app
```

## Verify
```bash
pytest
```

## Tradeoffs
- What this project does not try to do yet."""

PACKAGE_JSON_TEMPLATE = """{
  "name": "my-frontend",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "vitest": "^2.0.0"
  }
}"""

VITEST_TEMPLATE = """// src/App.test.tsx
import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the heading", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /hello/i })).toBeInTheDocument();
});"""

TSCONFIG_TEMPLATE = """{
  "compilerOptions": {
    "strict": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx"
  }
}"""

STYLING_TEMPLATE = """/* Component.module.css */
.card {
  display: grid;
  gap: 1rem;
  padding: 1rem;
  border-radius: 0.75rem;
  background: var(--surface-muted);
}"""

TERRAFORM_TEMPLATE = """# main.tf
resource "aws_instance" "app" {
  ami           = "ami-0abcdef1234567890"
  instance_type = "t3.micro"

  tags = { Name = "app" }
}"""

OBSERVABILITY_TEMPLATE = """# prometheus.yml
scrape_configs:
  - job_name: app
    metrics_path: /metrics
    static_configs:
      - targets: ["app:8000"]"""

SECRETS_TEMPLATE = """# .env.example (committed, placeholder values only)
DATABASE_URL=postgresql://user:secret@host:5432/db
API_KEY=replace-me

# .env (never committed; loaded at runtime)
DATABASE_URL=postgresql://real-user:real-secret@host:5432/db"""

DEPLOYMENT_TEMPLATE = """# render.yaml
services:
  - type: web
    name: app
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port 8000"""

FRONTEND_SCAFFOLD_TEMPLATE = """# Scaffold a modern frontend in one command
npm create vite@latest my-frontend -- --template react-ts
cd my-frontend
npm install
npm run dev"""


@dataclass(frozen=True)
class RubricRequirement:
    key: str
    title: str
    description: str
    evidence_keys: tuple[str, ...]
    action_title: str
    action_detail: str
    evidence_needed: tuple[str, ...]
    solution: str = ""
    template: str | None = None


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
            solution=(
                "Create a repository with a `pyproject.toml` or `requirements.txt` manifest, "
                "an `app/` or `src/` package, and a runnable entry point so reviewers can "
                "install and launch the project with two commands."
            ),
            template=PYTHON_PROJECT_TEMPLATE,
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
            solution=(
                "Add FastAPI, Django, or Flask to the manifest and expose at least one HTTP "
                "endpoint with a health route, request validation, and documented run command."
            ),
            template=FASTAPI_APP_TEMPLATE,
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
            solution=(
                "Add a `tests/` directory with pytest tests for core behavior and one failure "
                "path, plus a `pytest.ini` or `pyproject.toml` section that pins the test "
                "discovery command."
            ),
            template=PYTEST_TEMPLATE,
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
            solution=(
                "Declare a database driver or ORM and commit migration files (Alembic for "
                "SQLAlchemy, Django migrations, or Prisma) so the schema is versioned and "
                "reproducible."
            ),
            template=DATABASE_TEMPLATE,
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
            solution=(
                "Commit a GitHub Actions workflow that installs dependencies, runs the test "
                "suite, and runs static checks on every push and pull request."
            ),
            template=CI_TEMPLATE,
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
            solution=(
                "Add a production-focused Dockerfile with a pinned base image, dependency "
                "install step, non-root user, and a documented start command."
            ),
            template=DOCKERFILE_TEMPLATE,
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
            solution=(
                "Write a README that explains the problem, setup and verify commands, "
                "architecture, and the tradeoffs the project deliberately accepts."
            ),
            template=README_TEMPLATE,
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
            solution=(
                "Scaffold a frontend with a package manifest, a source directory, and one "
                "documented command that starts the development server."
            ),
            template=FRONTEND_SCAFFOLD_TEMPLATE,
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
            solution=(
                "Declare React, Vue, Svelte, or Angular in the package manifest and build a "
                "small interactive component that renders state and handles a user action."
            ),
            template=PACKAGE_JSON_TEMPLATE,
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
            solution=(
                "Add Vitest or Jest with Testing Library and cover one component render and "
                "one interaction path, then wire `npm test` as the single test command."
            ),
            template=VITEST_TEMPLATE,
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
            solution=(
                "Add CSS modules, Sass, or a utility framework and build a small set of "
                "reusable, themed components with consistent spacing and tokens."
            ),
            template=STYLING_TEMPLATE,
        ),
        RubricRequirement(
            key="frontend.typescript",
            title="Type-safe frontend",
            description="TypeScript is configured and used in the application.",
            evidence_keys=("frontend.typescript",),
            action_title="Adopt TypeScript",
            action_detail=("Add a tsconfig.json and type the core data flow of the application."),
            evidence_needed=("tsconfig.json", "TypeScript source files"),
            solution=(
                "Add a strict `tsconfig.json` and convert the core data flow of the app to "
                "typed TypeScript modules."
            ),
            template=TSCONFIG_TEMPLATE,
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
            solution=(
                "Commit a GitHub Actions workflow that installs dependencies, runs the test "
                "suite, and runs static checks on every push and pull request."
            ),
            template=CI_TEMPLATE,
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
            solution=(
                "Add a multi-stage Dockerfile that builds static assets and serves them from a "
                "non-root user with a documented start command."
            ),
            template=DOCKERFILE_TEMPLATE,
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
            solution=(
                "Write a README that explains the problem, setup and verify commands, "
                "architecture, and the tradeoffs the project deliberately accepts."
            ),
            template=README_TEMPLATE,
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
            solution=(
                "Add a production-focused Dockerfile or Compose setup with pinned base images, "
                "a non-root user, health checks, and a documented startup."
            ),
            template=DOCKERFILE_TEMPLATE,
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
            solution=(
                "Commit a GitHub Actions workflow that installs dependencies, runs the test "
                "suite, and runs static checks on every push and pull request."
            ),
            template=CI_TEMPLATE,
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
            solution=(
                "Commit a Terraform, CloudFormation, Ansible, or Kubernetes manifest that "
                "describes a small reproducible infrastructure, and document the apply or plan "
                "command."
            ),
            template=TERRAFORM_TEMPLATE,
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
            solution=(
                "Expose structured logs, metrics, or tracing from the app and commit the "
                "scraper or exporter configuration that collects them."
            ),
            template=OBSERVABILITY_TEMPLATE,
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
            solution=(
                "Read secrets from environment variables or a secret manager, and commit only "
                "an `.env.example` with placeholder values."
            ),
            template=SECRETS_TEMPLATE,
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
            solution=(
                "Add a service or deployment definition (platform config, Docker Compose, or "
                "Kubernetes) with documented run and rollback steps."
            ),
            template=DEPLOYMENT_TEMPLATE,
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
            solution=(
                "Write a README that explains the problem, setup and verify commands, "
                "architecture, and the tradeoffs the project deliberately accepts."
            ),
            template=README_TEMPLATE,
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
