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
ANALYZER_VERSION = "evidence-v1"
DEPENDENCY_SEPARATOR = re.compile(r"[\s<>=!~;\[]")

TECHNOLOGY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FastAPI", ("fastapi",)),
    ("Django", ("django",)),
    ("Flask", ("flask",)),
    ("SQLAlchemy", ("sqlalchemy", "sqlmodel")),
    ("Alembic", ("alembic",)),
    ("Pydantic", ("pydantic",)),
    ("PostgreSQL", ("psycopg", "psycopg2", "asyncpg")),
    ("MongoDB", ("pymongo", "motor")),
    ("Redis", ("redis", "redis-py")),
    ("Celery", ("celery",)),
    ("pytest", ("pytest",)),
    ("React", ("react", "react-dom")),
    ("Vue", ("vue",)),
    ("Svelte", ("svelte",)),
    ("Angular", ("@angular/core",)),
    ("TypeScript", ("typescript",)),
    ("Tailwind CSS", ("tailwindcss",)),
    ("Vitest", ("vitest",)),
    ("Jest", ("jest",)),
    ("Playwright", ("playwright",)),
    ("Cypress", ("cypress",)),
    ("GraphQL", ("graphene", "strawberry-graphql", "graphql")),
    ("NumPy", ("numpy",)),
    ("Pandas", ("pandas",)),
    ("Terraform", ("terraform",)),
    ("Ansible", ("ansible",)),
    ("Kubernetes", ("kubernetes",)),
    ("Prometheus", ("prometheus",)),
    ("Grafana", ("grafana",)),
    ("OpenTelemetry", ("opentelemetry",)),
)

PATH_TECHNOLOGY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Docker", ("dockerfile", "docker-compose", "compose.")),
    ("GitHub Actions", (".github/workflows/",)),
    ("Kubernetes", ("k8s", "kubernetes", "helm")),
    ("Terraform", (".tf", "terraform")),
    ("Ansible", ("ansible/",)),
    ("Prometheus", ("prometheus",)),
    ("Grafana", ("grafana",)),
    ("OpenTelemetry", ("opentelemetry", "otel")),
)


def extract_technologies(
    dependencies: Iterable[str],
    file_paths: Iterable[str],
) -> list[str]:
    found: set[str] = set()
    dependency_set = set(dependencies)
    for technology, hints in TECHNOLOGY_HINTS:
        if any(hint in dependency_set for hint in hints):
            found.add(technology)
    lower_paths = [path.lower() for path in file_paths]
    for technology, hints in PATH_TECHNOLOGY_HINTS:
        if any(hint in path for path in lower_paths for hint in hints):
            found.add(technology)
    return sorted(found)


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


class RepositoryAnalyzer:
    """Detect role-specific evidence from a single repository inspection."""

    def __init__(self, inspection: RepositoryInspection) -> None:
        self.inspection = inspection
        self.paths = sorted(
            inspection.file_paths,
            key=lambda path: (len(PurePosixPath(path).parts), path.lower()),
        )
        self.lower = {path: path.lower() for path in self.paths}
        self.dependencies = set(inspection.dependencies)
        self.manifest = inspection.manifest_paths[0] if inspection.manifest_paths else None
        self.items: list[EvidenceItem] = []

    def add(self, key: str, category: str, claim: str, evidence_paths: list[str]) -> None:
        self.items.append(
            EvidenceItem(
                key=key,
                category=category,
                claim=claim,
                repository=self.inspection.repository_full_name,
                sources=[source(self.inspection, path) for path in evidence_paths],
            )
        )

    def first(self, predicate: Callable[[str], bool]) -> str | None:
        return first_path(self.paths, predicate)

    def shared(self) -> None:
        workflow = self.first(lambda path: self.lower[path].startswith(".github/workflows/"))
        docker = self.first(
            lambda path: (
                self.lower[path].split("/")[-1] == "dockerfile"
                or self.lower[path].split("/")[-1].startswith("docker-compose")
                or self.lower[path].split("/")[-1].startswith("compose.")
            )
        )
        documentation = self.first(
            lambda path: (
                self.lower[path].split("/")[-1].startswith("readme")
                or self.lower[path].startswith("docs/")
            )
        )
        if workflow:
            self.add(
                "automation.github_actions",
                "automation",
                "GitHub Actions workflow configuration is present.",
                [workflow],
            )
        if docker:
            self.add(
                "delivery.container",
                "delivery",
                "Container build or orchestration configuration is present.",
                [docker],
            )
        if documentation:
            self.add(
                "documentation.project",
                "documentation",
                "Project documentation is present.",
                [documentation],
            )

    def python(self) -> None:
        python_file = self.first(lambda path: self.lower[path].endswith(".py"))
        test_file = self.first(
            lambda path: (
                self.lower[path].startswith(("test/", "tests/"))
                or self.lower[path].split("/")[-1].startswith("test_")
            )
        )
        pytest_config = self.first(
            lambda path: (
                self.lower[path] in {"pytest.ini", "tox.ini"}
                or self.lower[path].endswith("/pytest.ini")
            )
        )
        database_file = self.first(
            lambda path: (
                self.lower[path] == "alembic.ini"
                or self.lower[path].startswith(("migrations/", "alembic/"))
            )
        )
        test_setup = pytest_config or self.manifest
        if python_file and self.manifest:
            self.add(
                "python.project",
                "language",
                "Python source code and a dependency manifest are present.",
                [python_file, self.manifest],
            )
        if test_file and test_setup and ("pytest" in self.dependencies or pytest_config):
            self.add(
                "testing.pytest",
                "testing",
                "Automated Python tests use a recognized pytest setup.",
                [test_file, test_setup],
            )
        framework_labels = {"fastapi": "FastAPI", "django": "Django", "flask": "Flask"}
        for framework, label in framework_labels.items():
            if framework in self.dependencies and self.manifest:
                self.add(
                    f"api.framework.{framework}",
                    "api",
                    f"{label} is declared as a project dependency.",
                    [self.manifest],
                )
        database_dependencies = sorted(
            self.dependencies.intersection(
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
        if database_dependencies and self.manifest:
            evidence_paths = [self.manifest]
            if database_file:
                evidence_paths.append(database_file)
            self.add(
                "database.tooling",
                "database",
                f"Database tooling is declared: {', '.join(database_dependencies)}.",
                evidence_paths,
            )

    def frontend(self) -> None:
        source_file = self.first(
            lambda path: self.lower[path].endswith((".ts", ".tsx", ".js", ".jsx"))
        )
        package_json = self.first(lambda path: self.lower[path].split("/")[-1] == "package.json")
        test_file = self.first(
            lambda path: (
                self.lower[path].startswith(("test/", "tests/", "__tests__/"))
                or ".test." in self.lower[path]
                or ".spec." in self.lower[path]
            )
        )
        ts_config = self.first(
            lambda path: self.lower[path].split("/")[-1] in {"tsconfig.json", "tsconfig.build.json"}
        )
        style_file = self.first(
            lambda path: self.lower[path].endswith((".css", ".scss", ".sass", ".less"))
        )
        if source_file and package_json:
            self.add(
                "frontend.app",
                "frontend",
                "Frontend source code and a package manifest are present.",
                [source_file, package_json],
            )
        framework_keys = {
            "react": "react",
            "react-dom": "react",
            "vue": "vue",
            "svelte": "svelte",
            "@angular/core": "angular",
        }
        for dependency, key in framework_keys.items():
            if dependency in self.dependencies and package_json:
                self.add(
                    f"frontend.framework.{key}",
                    "frontend",
                    f"Framework {key} is declared as a project dependency.",
                    [package_json],
                )
        if test_file and package_json:
            runner = any(
                runner in self.dependencies
                for runner in ("vitest", "jest", "@testing-library/react", "playwright", "cypress")
            )
            if runner:
                self.add(
                    "frontend.testing",
                    "testing",
                    "Frontend automated tests use a recognized runner.",
                    [test_file, package_json],
                )
        if style_file:
            self.add(
                "frontend.styling",
                "frontend",
                "A styling system is present in source.",
                [style_file],
            )
        if ts_config and self.first(lambda path: self.lower[path].endswith((".ts", ".tsx"))):
            self.add(
                "frontend.typescript",
                "frontend",
                "TypeScript is configured and used in source.",
                [ts_config],
            )

    def devops(self) -> None:
        iac = self.first(
            lambda path: (
                self.lower[path].endswith((".tf", ".tf.json"))
                or self.lower[path].startswith(("terraform/", "ansible/"))
                or self.lower[path].endswith((".yml", ".yaml"))
                and any(
                    segment in self.lower[path]
                    for segment in ("deployment", "service", "k8s", "kubernetes", "helm")
                )
            )
        )
        observability = self.first(
            lambda path: any(
                segment in self.lower[path]
                for segment in ("prometheus", "grafana", "datadog", "otel", "opentelemetry")
            )
        )
        secrets = self.first(
            lambda path: (
                self.lower[path].split("/")[-1] in {".env.example", ".env.sample"}
                or "secrets" in self.lower[path]
            )
        )
        servicing = self.first(
            lambda path: any(
                segment in self.lower[path]
                for segment in ("deployment", "service.yaml", "workflow", "helm")
            )
        )
        if iac:
            self.add(
                "infrastructure.as_code",
                "infrastructure",
                "Infrastructure is managed as code.",
                [iac],
            )
        if observability:
            self.add(
                "infrastructure.observability",
                "infrastructure",
                "Observability configuration is present.",
                [observability],
            )
        if secrets:
            self.add(
                "infrastructure.secrets",
                "infrastructure",
                "Secret handling is defined without hard-coded credentials.",
                [secrets],
            )
        if servicing:
            self.add(
                "infrastructure.servicing",
                "infrastructure",
                "Deployment or service configuration is present.",
                [servicing],
            )

    def run(self, target_role: str) -> list[EvidenceItem]:
        self.shared()
        if target_role == "python_backend_developer":
            self.python()
        elif target_role == "frontend_developer":
            self.frontend()
        elif target_role == "devops_engineer":
            self.devops()
        return self.items


def analyze_repository(
    inspection: RepositoryInspection,
    target_role: str,
) -> list[EvidenceItem]:
    return RepositoryAnalyzer(inspection).run(target_role)


def analyze_evidence(snapshot: GitHubSnapshot, target_role: str) -> EvidenceSnapshot:
    rubric = get_rubric(target_role)
    items = [
        item
        for inspection in sorted(
            snapshot.inspections,
            key=lambda value: value.repository_full_name,
        )
        for item in analyze_repository(inspection, target_role)
    ]
    technologies = sorted(
        {
            technology
            for inspection in snapshot.inspections
            for technology in extract_technologies(
                inspection.dependencies,
                inspection.file_paths,
            )
        }
    )
    return EvidenceSnapshot(
        schema_version=SCHEMA_VERSION,
        analyzer_version=ANALYZER_VERSION,
        target_role=target_role,
        rubric_version=rubric.version,
        repositories_analyzed=len(snapshot.inspections),
        technologies=technologies,
        items=items,
    )
