# DevDNA

Evidence-based developer intelligence for developers and hiring teams.

DevDNA analyzes meaningful GitHub project evidence—such as tests, CI, documentation, APIs, databases, and deployment configuration—to produce explainable role-alignment reports, improvement roadmaps, and README drafts. It does not treat commit counts, contribution streaks, stars, or followers as skill scores.

## First release

`GitHub username + target role → explainable developer report`

The report must identify every strength, gap, and recommendation with the repository evidence that supports it.

## Repository layout

```text
src/devdna/     FastAPI service and analysis code
docs/           product, architecture, security, and delivery decisions
migrations/     versioned PostgreSQL schema changes
tests/          API and service tests
compose.yaml    local API, worker, PostgreSQL, and Redis stack
```

Read [the product specification](docs/PRODUCT_SPEC.md), [architecture](docs/ARCHITECTURE.md), and [delivery plan](docs/DELIVERY_PLAN.md) before implementation.

## Local development

Install `uv`, then:

```bash
uv sync --dev
uv run uvicorn devdna.main:app --reload
```

Run all checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Create and apply database migrations after changing models:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

With Docker installed, start the complete stack:

```bash
docker compose up --build
```

Submit a public GitHub profile analysis:

```bash
curl -X POST http://localhost:8000/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{"github_username":"octocat","target_role":"python_backend_developer"}'
```

Use the returned `id` to retrieve its status and snapshot. A completed snapshot includes the public profile and up to 10 recently pushed, non-fork, non-archived owner repositories:

```bash
curl http://localhost:8000/v1/analyses/ANALYSIS_ID
```

Submitting the same username and target role while an analysis is queued or running returns the existing analysis instead of creating duplicate work. Successful GitHub responses are cached in Redis for 24 hours and revalidated with ETags. Transient GitHub failures are retried twice with bounded delays; rate-limit failures report GitHub's reset time.
