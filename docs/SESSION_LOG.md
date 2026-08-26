# DevDNA — build session log

**Date:** 25 August 2026
**Branch:** `main`
**Final commit this session:** `054cd67` (CI green)
**Tests at end of session:** 120 passing, ruff + mypy strict clean

This document records what was built, verified, and deliberately left out during the working
session that took DevDNA from milestone-complete to a live-verified product.

## Starting state

- All 11 delivery milestones marked complete; 102 tests green.
- Pending report and recruiter pages refreshed with `<meta http-equiv="refresh">` every 3 s.

## What was built, in order

### 1. Live status polling (commit `760b743`)

- New `web_assets/app.js`: fetch-based poller replaces meta-refresh on pending report and
  recruiter batch pages. Staged copy for queued/running, animated fade-out redirect on completion,
  backoff + reconnect notice after three network misses, five-minute cap, inline failure state.
- IntersectionObserver scroll reveals for below-fold sections, honoring reduced motion; pages
  remain usable without JavaScript.

### 2. Job-description alignment (commit `88abf1c`)

- `jd.py`: deterministic 15-skill catalog mapped to real evidence keys. A demand verifies only
  through saved repository evidence with source links; unmet demands order by demand frequency.
- `POST /v1/analyses/{id}/jd-alignment` (owner-scoped) plus responsive form/result flow at
  `/reports/{id}/jd` linked from the report tools grid.
- Recruiter candidate rows gained capability chips derived from distinct evidence keys.
- Shared test-client helpers extracted to `tests/conftest.py`.

### 3. Deep-search activity intelligence (commit `054cd67`)

- Discovery: GitHub's public events feed frequently strips push payloads — commit messages were
  missing for active users (verified against dhh).
- Worker now reads real commits directly from the developer's selected repositories
  (`/repos/{repo}/commits?author=user`, bounded to 5 repos × 30 commits) and merges them with
  event-feed signals (merged PRs, opened issues, OSS share, touched repositories).
- `activity.py`: conventional-commit classifier (`feat/fix/perf/refactor/test/docs`) with noise
  filters for merges, bot bumps, chores, and placeholder messages.
- Report page renders a Recent impact section: stat tiles, notable commits with kind badges and
  per-commit links, merged pull requests — styled and animated within the existing system.
- Recruiter uploads accept PDF and extract bare/punctuated github.com links plus @mentions from
  free-form CSV/DOCX/PDF text, so a candidate CV works as the batch file.
- README studio gained a copy-to-clipboard button with fallback.

### 4. Command-line interface (commit pending at time of writing)

- `src/devdna/cli.py`: `devdna` console entry point (pyproject `[project.scripts]`) with
  subcommands analyze/status/report/readme/learning/jd/cv/history/health.
- `--wait` polls until terminal status with timeout; `--json` for raw payloads; bearer key
  support via `DEVDNA_API_KEY`; exit codes 0/1/2; broken-pipe safe for pager piping.
- Verified live: health, analyze --wait through real worker, pretty report with sources,
  README file download, JD backlog ordering, history listing.

## Live verification performed

| Check | Result |
| --- | --- |
| Full Docker stack | api + worker + postgres + redis healthy |
| Real analysis: octocat / python role | completed; honest 1/7 coverage with source links |
| Real analysis: gaearon / React role | partial path exercised live; 7/8 verified |
| Real analysis: dhh / deep activity | 17 commits analyzed, 12 meaningful, 99% OSS share |
| JD alignment vs real description | 0/7 honest result, frequency-ordered backlog rendered |
| Recruiter batch via API | capabilities surfaced from real evidence keys |
| Load smoke | 200 requests, 0 errors, p95 ≈ 51–55 ms (limit 500 ms) |
| Backup + restore round-trip | both analyses survived pg_restore and re-migration |
| Retention command | ran via compose maintenance profile |
| Staging boot gate | rejects missing secrets; boots with valid ones |
| Secret scan | clean |
| CI | green on every pushed commit |

## Deliberately left out

External accounts or product decisions are prerequisites, not code:

1. Real deployment (Render account; `render.yaml` ready).
2. Clerk publishable/secret keys for sign-in activation.
3. `DEVDNA_GITHUB_TOKEN` for 5,000 req/hour inspection budget.
4. Private-repository access (GitHub App OAuth) — public-only by design for release 1.
5. LLM-assisted summaries — must stay constrained to saved evidence JSON if introduced.
6. Per-commit diff-depth analysis — multiplies API cost; deferred until a token-bearing
   deployment justifies it.
