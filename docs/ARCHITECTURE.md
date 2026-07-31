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
| FastAPI API | Bearer API-key authentication for writes; request validation; create/read analyses; per-client rate limiting; health and metrics endpoints. |
| Worker | Collect GitHub data, select repositories, run evidence rules, create report artifacts. |
| PostgreSQL | Users, immutable analysis runs, repository snapshots, evidence, role rubrics, recommendations. |
| Redis | Queue, short-lived rate-limit counters, distributed locks, cache. |
| GitHub adapter | Typed API client, pagination, retries, conditional requests, rate-limit awareness. |

## Analysis lifecycle

1. Validate `github_username` and `target_role`.
2. Authenticate the caller in production and atomically apply its Redis request limit.
3. Return an existing active analysis when the username and role already have queued work.
4. Otherwise create an `analysis_run` and enqueue one idempotent job.
5. Worker fetches user and repositories, then selects meaningful non-fork, non-archived projects.
6. Worker records raw snapshot facts and derives evidence with deterministic rules.
7. Worker maps evidence to the role rubric and persists a versioned report.
8. Optional LLM summary uses only the persisted evidence JSON schema.

## Core data entities

```text
analysis_runs(id, github_username, role_id, status, analyzer_version, requested_at, completed_at)
repositories(id, analysis_run_id, github_id, name, url, snapshot_json)
evidence(id, repository_id, category, claim, source_path, source_url, confidence)
role_rubrics(id, slug, version, definition_json)
reports(id, analysis_run_id, rubric_version, report_json)
```

The current release stores the immutable public GitHub collection in `profile_snapshot`, the deterministic analyzer output in `evidence_snapshot`, and the versioned explainable result in `report_snapshot` on each analysis run. This keeps the first report contract atomic and reproducible. Normalize repositories and evidence into dedicated tables when recruiter queries or cross-analysis reporting require indexed access.

## Cache and rate-limit policy

- Cache public GitHub responses with ETags and `If-None-Match` where available.
- Cache a completed analysis by `(username, role, analyzer_version, rubric_version)` for 24 hours initially.
- Store GitHub rate-limit headers after every request; pause/retry jobs at reset time rather than failing the whole batch.
- Cap repository inspection in release 1 (for example, 10 selected repositories) to bound latency and API usage.
- Use exponential backoff with jitter for transient `429` and `5xx` responses. Do not retry invalid requests or missing users.
- Use a Redis lock keyed by analysis cache key so duplicate requests create one job.
- Limit `POST /v1/analyses` with an atomic Redis fixed-window counter. The current direct-peer IP key is safe for direct deployment; configure trusted proxy addresses before accepting forwarded client IPs.
- Fail analysis creation closed when Redis cannot enforce the limit. Return the limit, remaining count, and retry interval in standard response headers.

## Operations and observability

- Structured request and exception logs include a validated request ID, route template, response status, duration, and authenticated client identifier.
- `/metrics` exposes process-local Prometheus counters and duration summaries with bounded route labels. The deployment restricts this endpoint to its monitoring network.
- Terminal analysis records expire after 90 days by default through an externally scheduled, bounded maintenance command. Active work is excluded.
- PostgreSQL custom-format backups are verified when created; restore stops writers, reapplies migrations, and restarts services.
- CI checks the migration head against PostgreSQL, builds the runtime image, and runs the complete static and automated test gate.

## Security and privacy baseline

- Begin with public GitHub data only.
- Keep secrets in deployment environment variables; never return them in logs or API responses.
- Bound mutation request bodies and apply content-type, framing, referrer, permissions, and report-page content security headers in the API.
- CV alignment parses bounded PDF/DOCX uploads in memory and compares them only with the immutable
  saved evidence snapshot; raw bytes and extracted text never enter the database.
- Encrypt OAuth tokens at rest when OAuth is added.
- Do not store CV content. Recruitment-list metadata follows the configured retention policy.
- Recruitment features must not infer protected traits or make autonomous selection/rejection decisions.

## Market-signal governance

Role-gap recommendations are deterministic outputs of the versioned role rubric. Optional market
signals live in a separate catalog with a primary source URL and explicit review date. They may
suggest portfolio exploration but cannot create evidence, change role coverage, or influence a
future hiring rank. Review or remove stale signals before their dated source no longer represents
the current ecosystem.
