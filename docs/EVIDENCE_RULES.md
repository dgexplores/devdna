# Evidence rules

## Contract

Analyzer `python-backend-evidence-v1` uses rubric `python_backend_developer:v1`. It inspects at most 10 selected owner repositories, stores at most 5,000 file paths per repository, and reads at most two Python dependency manifests of at most 100 KB each.

The saved inspection facts are:

- repository and default branch;
- bounded file paths and whether GitHub truncated the tree;
- successfully read manifest paths;
- normalized dependency names.

Every evidence item identifies one repository and one or more GitHub file links. Missing or inaccessible data produces no claim. A failed or truncated repository inspection makes the analysis partial and adds a visible warning.

## Version 1 rules

| Evidence key | Required facts |
|---|---|
| `python.project` | Python source file and a successfully read Python manifest. |
| `testing.pytest` | Test file plus pytest dependency or pytest configuration. |
| `automation.github_actions` | File under `.github/workflows/`. |
| `delivery.container` | Dockerfile, Compose, or docker-compose configuration. |
| `documentation.project` | README or file under `docs/`. |
| `api.framework.fastapi` | FastAPI dependency in a read manifest. |
| `api.framework.django` | Django dependency in a read manifest. |
| `api.framework.flask` | Flask dependency in a read manifest. |
| `database.tooling` | Recognized database dependency, optionally supported by Alembic or migrations paths. |

The analyzer does not use commits, streaks, stars, followers, repository popularity, or self-declared profile text as evidence of engineering ability.
