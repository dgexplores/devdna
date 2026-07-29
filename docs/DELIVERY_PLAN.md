# Delivery plan

## Working method

Every increment follows: define acceptance criteria → implement smallest vertical slice → add focused tests → run locally in Docker → review logs/metrics → merge. Avoid building the recruiter product before the developer analysis engine is reliable.

## Milestone 0 — foundation

**Status:** completed on 30 July 2026. Python checks pass, the Docker stack builds and starts, migrations complete, and both API health endpoints pass against PostgreSQL and Redis.

- Python project tooling, formatting, linting, type checking, pytest.
- FastAPI health endpoint.
- PostgreSQL, Redis, Docker Compose.
- CI running tests and static checks.
- Configuration validation and structured JSON logs.

**Done when:** a new clone starts the API, worker, database, and Redis with one documented command; CI is green.

## Milestone 1 — reliable GitHub collection

**Status:** profile and bounded repository collection completed on 30 July 2026. A validated request is persisted, queued, and processed by the worker. DevDNA follows repository pagination when necessary, selects up to 10 recently pushed owner repositories, excludes forks/archived/disabled/empty repositories, and preserves rate-limit metadata. ETag caching, duplicate suppression, and retry scheduling remain in this milestone.

- `POST /v1/analyses` and `GET /v1/analyses/{id}`.
- Background job state machine: queued, running, completed, partial, failed.
- Typed GitHub client, pagination, retries, ETag cache, rate-limit handling.
- Persist a raw public profile and repository snapshot.

**Done when:** known public accounts are analyzed without duplicate jobs, and GitHub outages/rate limits produce a recoverable state.

## Milestone 2 — evidence engine

- Repository selection rules.
- File-tree and dependency analysis.
- Rules for tests, CI, Docker, docs, API, database, and Python framework evidence.
- Versioned `python_backend_developer` rubric.

**Done when:** fixture repositories produce stable, source-linked evidence and no conclusion is generated from commit/streak metrics.

## Milestone 3 — explainable report

- Role alignment, strengths, gaps, and prioritised actions.
- API report schema and a minimal web report page.
- Optional LLM summary constrained to evidence JSON.

**Done when:** each report claim includes a repository URL and evidence reason.

## Milestone 4 — production hardening

- Authentication and per-user API throttling.
- Monitoring, error tracking, backups, migrations, retention policy, load testing.
- GitHub App OAuth and opt-in private-repository access only if justified.

## Test strategy

- Unit tests: evidence rules and rubric matching.
- Contract tests: GitHub adapter fixtures, including pagination and rate-limit responses.
- Integration tests: API → queue → database lifecycle.
- End-to-end smoke test: submit a known public username and assert a completed, evidence-backed report.
- Security checks: secret scan, dependency updates, input validation tests.
