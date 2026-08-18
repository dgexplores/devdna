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

Read [the product specification](docs/PRODUCT_SPEC.md), [architecture](docs/ARCHITECTURE.md), [security baseline](docs/SECURITY.md), [operations runbook](docs/OPERATIONS.md), and [delivery plan](docs/DELIVERY_PLAN.md) before implementation.

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

Open `http://localhost:8000` to start an analysis from the responsive web interface. The form
validates the account, starts the background job, and shows progress until the evidence report is
ready. When `DEVDNA_API_KEYS` is configured, the page asks for the same `client.secret` access key
used by the API and never stores or reflects it.

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

Analysis creation is limited to 10 requests per direct client IP per 60-second window. Mutation requests require `Content-Length` and their bodies are capped at 16 KiB; Redis failure closes analysis creation with `503` instead of bypassing the limit. Override these deployment settings with `DEVDNA_ANALYSIS_RATE_LIMIT`, `DEVDNA_ANALYSIS_RATE_WINDOW_SECONDS`, and `DEVDNA_MAX_REQUEST_BYTES`. Configure a trusted-proxy allowlist before using forwarded client IP headers.

Staging and production require `DEVDNA_API_KEYS` with comma-separated `client=secret` entries. Create analyses with `Authorization: Bearer client.secret`; limits then apply independently to each client. Every response carries a request ID, and `/metrics` exposes bounded Prometheus-format request counters and durations.

Staging and production also require `DEVDNA_WEB_SESSION_SECRET`, an independent high-entropy
secret used to sign the web app's eight-hour HttpOnly session cookie. Override the duration with
`DEVDNA_WEB_SESSION_HOURS`. A valid web-form access key establishes the cookie; analysis history
is then available at `/history`. The bounded `GET /v1/analyses` endpoint returns only requests
owned by the authenticated API client.

If repository collection fails after the public profile succeeds, the analysis returns `partial` instead of discarding valid data. Its snapshot contains the profile and any repositories collected before the failure, while `error_message` explains what remains incomplete.

A completed or partial response also includes `evidence_snapshot`. Evidence version `python-backend-evidence-v1` derives only from saved repository file paths and normalized Python manifest dependencies. Every claim contains direct GitHub source links; commit counts and contribution streaks are not analyzer inputs. See [the evidence rules](docs/EVIDENCE_RULES.md).

Beyond the Python backend role, DevDNA supports the `frontend_react_developer` role end to end with
its own versioned rubric (`frontend_react_developer:v1`), React-specific evidence rules that read
bounded `package.json` manifests, role-scoped report and learning-plan versions, and recruiter
comparison. Submit it with `"target_role": "frontend_react_developer"`.

The worker converts that evidence into `report_snapshot`, containing verified strengths, unverified rubric requirements, and prioritized actions. Retrieve the typed report at:

```bash
curl http://localhost:8000/v1/analyses/ANALYSIS_ID/report
```

Open the responsive evidence report at `http://localhost:8000/reports/ANALYSIS_ID`. Reports show transparent requirement coverage rather than a universal developer score. See [the report contract](docs/REPORT_CONTRACT.md).

The report adds project context next to the evidence spine: language share from each inspected repository, public organization memberships, and a detected technology stack (from manifest dependencies and file paths). Language and organization data inform display only, never rubric scoring. Every improvement action carries an expandable starter solution with a code template sized to the role rubric.

Reports and their README and learning pages are readable by anyone with the analysis ID because they contain public GitHub evidence only. Private data stays gated: analysis history requires the session or API key, and CV alignment and recruiter batches verify ownership.

Each completed report links to an evidence-constrained profile README workspace at
`http://localhost:8000/reports/ANALYSIS_ID/readme`. The draft features only repositories and
engineering practices verified by the saved report, labels improvement work as aspirational, and
can be downloaded as `README.md`. Its typed JSON form is available at
`/v1/analyses/ANALYSIS_ID/readme`; DevDNA never publishes the draft automatically. The studio
switches between three layouts — `minimal`, `badges`, and `centered` — via `?style=` on the page,
the download, and the API.

The README workspace can privately compare a PDF or DOCX CV with the saved GitHub evidence.
Verified and CV-only skills are shown separately; CV-only statements never become verified claims.
Uploaded bytes and extracted text are processed in memory and are not stored. Authenticated API
clients can use `POST /v1/analyses/ANALYSIS_ID/cv-alignment` with a multipart `file` field.

The report also links to `http://localhost:8000/reports/ANALYSIS_ID/learning`, which turns each
unverified role requirement into learning outcomes, a portfolio project, and an evidence checklist.
Its final section contains separately labeled, dated market signals with primary sources. These
signals do not affect the evidence report. The typed plan is available at
`/v1/analyses/ANALYSIS_ID/learning`.

Authenticated recruiter users can open `/recruiter` and upload a CSV or DOCX containing public
GitHub usernames. The batch reuses the same evidence engine and compares candidates only by
verified coverage of the selected role rubric. Pending candidates remain unranked, every result
opens its evidence report, and the interface explicitly requires human review. The API endpoints
are `POST /v1/recruiter/batches` and `GET /v1/recruiter/batches/BATCH_ID`.

Production operations include a 90-day terminal-analysis retention command, verified PostgreSQL backup/restore scripts, migration checks in CI, dependency update automation, and a bounded read-path load smoke test. Exact commands and failure procedures are in [the operations runbook](docs/OPERATIONS.md).

Stop local services without deleting PostgreSQL or Redis volumes:

```bash
docker compose down
```
