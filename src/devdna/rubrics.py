from dataclasses import dataclass


@dataclass(frozen=True)
class RubricRequirement:
    key: str
    evidence_keys: tuple[str, ...]


@dataclass(frozen=True)
class RoleRubric:
    role: str
    version: str
    requirements: tuple[RubricRequirement, ...]


PYTHON_BACKEND_DEVELOPER = RoleRubric(
    role="python_backend_developer",
    version="python_backend_developer:v1",
    requirements=(
        RubricRequirement("python", ("python.project",)),
        RubricRequirement(
            "api_framework",
            ("api.framework.fastapi", "api.framework.django", "api.framework.flask"),
        ),
        RubricRequirement("testing", ("testing.pytest",)),
        RubricRequirement("database", ("database.tooling",)),
        RubricRequirement("automation", ("automation.github_actions",)),
        RubricRequirement("delivery", ("delivery.container",)),
        RubricRequirement("documentation", ("documentation.project",)),
    ),
)

RUBRICS = {PYTHON_BACKEND_DEVELOPER.role: PYTHON_BACKEND_DEVELOPER}


def get_rubric(role: str) -> RoleRubric:
    try:
        return RUBRICS[role]
    except KeyError as error:
        raise ValueError(f"unsupported role: {role}") from error
