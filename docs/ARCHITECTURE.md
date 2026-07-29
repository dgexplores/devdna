# Architecture

## Initial deployment shape

```text
Browser → FastAPI API → PostgreSQL
                    ↘ Redis queue → Python worker → GitHub API
```

Keep this as one deployable Python codebase with two processes: API and worker. Do not split into microservices until load, team ownership, or deployment boundaries justify it.

## Components

| Component | Responsibility |
|---|---|
| FastAPI API | Auth later; request validation; create/read analyses; rate limiting; status endpoints. |
| Worker | Collect GitHub data, select repositories, run evidence rules, create report artifacts. |
| PostgreSQL | Users, immutable analysis runs, repository snapshots, evidence, role rubrics, recommendations. |
| Redis | Queue, short-lived rate-limit counters, distributed locks, cache. |
| GitHub adapter | Typed API client, pagination, retries, conditional requests, rate-limit awareness. |

## Analysis lifecycle

1. Validate `github_username` and `target_role`.
2. Return an existing fresh completed analysis if its cache key matches.
3. Otherwise create an `analysis_run` and enqueue one idempotent job.
4. Worker fetches user and repositories, then selects meaningful non-fork, non-archived projects.
5. Worker records raw snapshot facts and derives evidence with deterministic rules.
6. Worker maps evidence to the role rubric and persists a versioned report.
7. Optional LLM summary uses only the persisted evidence JSON schema.

## Core data entities

```text
analysis_runs(id, github_username, role_id, status, analyzer_version, requested_at, completed_at)
repositories(id, analysis_run_id, github_id, name, url, snapshot_json)
evidence(id, repository_id, category, claim, source_path, source_url, confidence)
role_rubrics(id, slug, version, definition_json)
reports(id, analysis_run_id, rubric_version, report_json)
```

## Cache and rate-limit policy

- Cache public GitHub responses with ETags and `If-None-Match` where available.
- Cache a completed analysis by `(username, role, analyzer_version, rubric_version)` for 24 hours initially.
- Store GitHub rate-limit headers after every request; pause/retry jobs at reset time rather than failing the whole batch.
- Cap repository inspection in release 1 (for example, 10 selected repositories) to bound latency and API usage.
- Use exponential backoff with jitter for transient `429` and `5xx` responses. Do not retry invalid requests or missing users.
- Use a Redis lock keyed by analysis cache key so duplicate requests create one job.

## Security and privacy baseline

- Begin with public GitHub data only.
- Keep secrets in deployment environment variables; never return them in logs or API responses.
- Validate upload and URL inputs before future CV support.
- Encrypt OAuth tokens at rest when OAuth is added.
- Define retention/deletion controls before storing CVs or recruitment lists.
- Recruitment features must not infer protected traits or make autonomous selection/rejection decisions.
