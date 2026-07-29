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

**Status:** completed on 30 July 2026. A validated request is persisted, queued, and processed by the worker. DevDNA follows repository pagination when necessary, selects up to 10 recently pushed owner repositories, excludes forks/archived/disabled/empty repositories, and preserves rate-limit metadata. GitHub responses use a 24-hour Redis ETag cache, the database prevents duplicate active analyses, and transient profile failures receive two bounded retries. If repository collection fails after the profile succeeds, DevDNA preserves the profile and any repositories already collected as a partial result with a visible warning.

- `POST /v1/analyses` and `GET /v1/analyses/{id}`.
- Background job state machine: queued, running, completed, partial, failed.
- Typed GitHub client, pagination, retries, ETag cache, rate-limit handling.
- Persist a raw public profile and repository snapshot.

**Done when:** known public accounts are analyzed without duplicate jobs, and GitHub outages/rate limits produce a recoverable state.

## Milestone 2 — evidence engine

**Status:** completed on 30 July 2026. DevDNA inspects bounded repository trees and up to two Python manifests per selected repository, saves normalized inspection facts, and emits versioned, repository-specific evidence with direct GitHub source links. Fixture tests prove that absent manifests do not produce Python skill claims and that commit activity is never an evidence input.

- Repository selection rules.
- File-tree and dependency analysis.
- Rules for tests, CI, Docker, docs, API, database, and Python framework evidence.
- Versioned `python_backend_developer` rubric.

**Done when:** fixture repositories produce stable, source-linked evidence and no conclusion is generated from commit/streak metrics.

## Milestone 3 — explainable report

**Status:** completed on 30 July 2026. The worker deterministically maps versioned evidence to rubric strengths, gaps, transparent requirement coverage, and prioritized actions. Reports are persisted, exposed through a typed API, and rendered as a responsive evidence-spine page. Partial analyses explicitly distinguish unverified data from absent evidence.

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
