import re
import tomllib
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from urllib.parse import quote

from devdna.rubrics import get_rubric
from devdna.schemas import (
    EvidenceItem,
    EvidenceSnapshot,
    EvidenceSource,
    GitHubSnapshot,
    RepositoryInspection,
)

SCHEMA_VERSION = "1"
ANALYZER_VERSION = "python-backend-evidence-v1"
DEPENDENCY_SEPARATOR = re.compile(r"[\s<>=!~;\[]")


def normalize_dependency(value: str) -> str | None:
    candidate = DEPENDENCY_SEPARATOR.split(value.strip(), maxsplit=1)[0]
    if not candidate or candidate.startswith(("-", ".", "git+", "http:", "https:")):
        return None
    return candidate.lower().replace("_", "-")


def extract_dependencies(path: str, content: str) -> list[str]:
    lower_path = path.lower()
    values: list[str] = []
    if lower_path.endswith((".toml", "pipfile")):
        try:
            document = tomllib.loads(content)
        except tomllib.TOMLDecodeError:
            return []
        project = document.get("project", {})
        values.extend(project.get("dependencies", []))
        for dependencies in project.get("optional-dependencies", {}).values():
            values.extend(dependencies)
        poetry = document.get("tool", {}).get("poetry", {})
        values.extend(poetry.get("dependencies", {}).keys())
        for group in poetry.get("group", {}).values():
            values.extend(group.get("dependencies", {}).keys())
        values.extend(document.get("packages", {}).keys())
        values.extend(document.get("dev-packages", {}).keys())
    elif "requirements" in lower_path:
        values.extend(
            line
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-"))
        )

    normalized = {dependency for value in values if (dependency := normalize_dependency(value))}
    normalized.discard("python")
    return sorted(normalized)


def source(inspection: RepositoryInspection, path: str) -> EvidenceSource:
    encoded = quote(
        f"{inspection.repository_full_name}/blob/{inspection.default_branch}/{path}",
        safe="/",
    )
    return EvidenceSource(
        repository=inspection.repository_full_name,
        path=path,
        url=f"https://github.com/{encoded}",
    )


def first_path(paths: Iterable[str], predicate: Callable[[str], bool]) -> str | None:
    return next((path for path in paths if predicate(path)), None)


def analyze_repository(inspection: RepositoryInspection) -> list[EvidenceItem]:
    paths = sorted(
        inspection.file_paths,
        key=lambda path: (len(PurePosixPath(path).parts), path.lower()),
    )
    lower = {path: path.lower() for path in paths}
    dependencies = set(inspection.dependencies)
    manifest = inspection.manifest_paths[0] if inspection.manifest_paths else None
    python_file = first_path(paths, lambda path: lower[path].endswith(".py"))
    test_file = first_path(
        paths,
        lambda path: (
            lower[path].startswith(("test/", "tests/"))
            or lower[path].split("/")[-1].startswith("test_")
        ),
    )
    pytest_config = first_path(
        paths,
        lambda path: (
            lower[path] in {"pytest.ini", "tox.ini"} or lower[path].endswith("/pytest.ini")
        ),
    )
    workflow = first_path(paths, lambda path: lower[path].startswith(".github/workflows/"))
    docker = first_path(
        paths,
        lambda path: (
            lower[path].split("/")[-1] == "dockerfile"
            or lower[path].split("/")[-1].startswith("docker-compose")
            or lower[path].split("/")[-1].startswith("compose.")
        ),
    )
    documentation = first_path(
        paths,
        lambda path: (
            lower[path].split("/")[-1].startswith("readme") or lower[path].startswith("docs/")
        ),
    )
    database_file = first_path(
        paths,
        lambda path: (
            lower[path] == "alembic.ini" or lower[path].startswith(("migrations/", "alembic/"))
        ),
    )
    test_setup = pytest_config or manifest

    items: list[EvidenceItem] = []

    def add(key: str, category: str, claim: str, evidence_paths: list[str]) -> None:
        items.append(
            EvidenceItem(
                key=key,
                category=category,
                claim=claim,
                repository=inspection.repository_full_name,
                sources=[source(inspection, path) for path in evidence_paths],
            )
        )

    if python_file and manifest:
        add(
            "python.project",
            "language",
            "Python source code and a dependency manifest are present.",
            [python_file, manifest],
        )
    if test_file and test_setup and ("pytest" in dependencies or pytest_config):
        add(
            "testing.pytest",
            "testing",
            "Automated Python tests use a recognized pytest setup.",
            [test_file, test_setup],
        )
    if workflow:
        add(
            "automation.github_actions",
            "automation",
            "GitHub Actions workflow configuration is present.",
            [workflow],
        )
    if docker:
        add(
            "delivery.container",
            "delivery",
            "Container build or orchestration configuration is present.",
            [docker],
        )
    if documentation:
        add(
            "documentation.project",
            "documentation",
            "Project documentation is present.",
            [documentation],
        )
    framework_labels = {"fastapi": "FastAPI", "django": "Django", "flask": "Flask"}
    for framework, label in framework_labels.items():
        if framework in dependencies and manifest:
            add(
                f"api.framework.{framework}",
                "api",
                f"{label} is declared as a project dependency.",
                [manifest],
            )
    database_dependencies = sorted(
        dependencies.intersection(
            {
                "alembic",
                "asyncpg",
                "django",
                "motor",
                "psycopg",
                "psycopg2",
                "psycopg2-binary",
                "pymongo",
                "sqlalchemy",
                "sqlmodel",
            }
        )
    )
    if database_dependencies and manifest:
        evidence_paths = [manifest]
        if database_file:
            evidence_paths.append(database_file)
        add(
            "database.tooling",
            "database",
            f"Database tooling is declared: {', '.join(database_dependencies)}.",
            evidence_paths,
        )
    return items


def analyze_evidence(snapshot: GitHubSnapshot, target_role: str) -> EvidenceSnapshot:
    rubric = get_rubric(target_role)
    items = [
        item
        for inspection in sorted(
            snapshot.inspections,
            key=lambda value: value.repository_full_name,
        )
        for item in analyze_repository(inspection)
    ]
    return EvidenceSnapshot(
        schema_version=SCHEMA_VERSION,
        analyzer_version=ANALYZER_VERSION,
        target_role=target_role,
        rubric_version=rubric.version,
        repositories_analyzed=len(snapshot.inspections),
        items=items,
    )
