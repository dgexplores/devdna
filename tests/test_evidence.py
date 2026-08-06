from devdna.evidence import analyze_evidence, extract_dependencies
from devdna.rubrics import get_rubric
from devdna.schemas import GitHubProfile, GitHubSnapshot, RepositoryInspection

PROFILE = GitHubProfile.model_validate(
    {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/octocat.png",
        "html_url": "https://github.com/octocat",
        "public_repos": 1,
        "followers": 1,
        "following": 0,
        "created_at": "2011-01-25T18:44:36Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
)


def test_extract_dependencies_from_python_manifests() -> None:
    pyproject = """
[project]
dependencies = ["FastAPI>=0.100", "SQLAlchemy[asyncio]~=2.0"]

[project.optional-dependencies]
test = ["pytest>=8"]
"""
    requirements = """
# runtime
uvicorn==0.35
-r shared.txt
asyncpg>=0.30
"""

    assert extract_dependencies("pyproject.toml", pyproject) == [
        "fastapi",
        "pytest",
        "sqlalchemy",
    ]
    assert extract_dependencies("requirements.txt", requirements) == ["asyncpg", "uvicorn"]


def test_analyze_evidence_emits_stable_source_linked_claims() -> None:
    inspection = RepositoryInspection(
        repository_full_name="octocat/backend",
        default_branch="main",
        file_paths=[
            ".github/workflows/ci.yml",
            "Dockerfile",
            "README.md",
            "alembic.ini",
            "pyproject.toml",
            "src/main.py",
            "tests/test_api.py",
        ],
        manifest_paths=["pyproject.toml"],
        dependencies=["alembic", "fastapi", "pytest", "sqlalchemy"],
    )
    snapshot = GitHubSnapshot(
        profile=PROFILE,
        inspections=[inspection],
        rate_limit_remaining=50,
        rate_limit_reset=123456,
    )

    evidence = analyze_evidence(snapshot, "python_backend_developer")
    by_key = {item.key: item for item in evidence.items}

    assert evidence.schema_version == "1"
    assert evidence.analyzer_version == "evidence-v1"
    assert evidence.rubric_version == "python_backend_developer:v1"
    assert evidence.repositories_analyzed == 1
    assert set(by_key) == {
        "api.framework.fastapi",
        "automation.github_actions",
        "database.tooling",
        "delivery.container",
        "documentation.project",
        "python.project",
        "testing.pytest",
    }
    assert by_key["python.project"].sources[0].url == (
        "https://github.com/octocat/backend/blob/main/src/main.py"
    )
    assert by_key["database.tooling"].sources[1].path == "alembic.ini"


def test_analyze_evidence_does_not_infer_python_without_manifest() -> None:
    snapshot = GitHubSnapshot(
        profile=PROFILE,
        inspections=[
            RepositoryInspection(
                repository_full_name="octocat/script",
                default_branch="main",
                file_paths=["main.py"],
            )
        ],
        rate_limit_remaining=50,
        rate_limit_reset=123456,
    )

    evidence = analyze_evidence(snapshot, "python_backend_developer")

    assert evidence.items == []


def test_frontend_analyzer_detects_framework_styling_and_tests() -> None:
    snapshot = GitHubSnapshot(
        profile=PROFILE,
        inspections=[
            RepositoryInspection(
                repository_full_name="octocat/web",
                default_branch="main",
                file_paths=[
                    ".github/workflows/ci.yml",
                    "Dockerfile",
                    "README.md",
                    "package.json",
                    "tsconfig.json",
                    "src/App.tsx",
                    "src/App.css",
                    "src/App.test.tsx",
                ],
                manifest_paths=["package.json"],
                dependencies=["react", "react-dom", "typescript", "vitest", "tailwindcss"],
            )
        ],
        rate_limit_remaining=50,
        rate_limit_reset=123456,
    )

    evidence = analyze_evidence(snapshot, "frontend_developer")
    by_key = {item.key: item for item in evidence.items}

    assert evidence.rubric_version == "frontend_developer:v1"
    assert "frontend.app" in by_key
    assert "frontend.framework.react" in by_key
    assert "frontend.styling" in by_key
    assert "frontend.typescript" in by_key
    assert "frontend.testing" in by_key
    assert "automation.github_actions" in by_key
    assert "delivery.container" in by_key
    assert "documentation.project" in by_key


def test_devops_analyzer_detects_infrastructure_as_code() -> None:
    snapshot = GitHubSnapshot(
        profile=PROFILE,
        inspections=[
            RepositoryInspection(
                repository_full_name="octocat/infra",
                default_branch="main",
                file_paths=[
                    ".github/workflows/deploy.yml",
                    "Dockerfile",
                    "README.md",
                    ".env.example",
                    "terraform/main.tf",
                    "k8s/deployment.yaml",
                    "prometheus/prometheus.yml",
                ],
            )
        ],
        rate_limit_remaining=50,
        rate_limit_reset=123456,
    )

    evidence = analyze_evidence(snapshot, "devops_engineer")
    by_key = {item.key: item for item in evidence.items}

    assert evidence.rubric_version == "devops_engineer:v1"
    assert "infrastructure.as_code" in by_key
    assert "infrastructure.observability" in by_key
    assert "infrastructure.secrets" in by_key
    assert "infrastructure.servicing" in by_key
    assert "automation.github_actions" in by_key
    assert "delivery.container" in by_key
    assert "documentation.project" in by_key


def test_role_registry_has_supported_roles() -> None:
    assert get_rubric("frontend_developer").role == "frontend_developer"
    assert get_rubric("devops_engineer").version == "devops_engineer:v1"
