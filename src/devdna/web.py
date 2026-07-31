from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.analyses import start_analysis
from devdna.database import get_session
from devdna.models import AnalysisRun
from devdna.rubrics import get_rubric
from devdna.schemas import AnalysisCreate, ReportAction, ReportGap, ReportSnapshot, ReportStrength
from devdna.security import enforce_analysis_creation_access

router = APIRouter(tags=["web"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ASSET_VERSION = "2"
FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='12' fill='%232457d6'/%3E"
    "%3Cpath d='M17 15h13c13 0 20 7 20 17s-7 17-20 17H17V15zm12 25c7 0 10-3 "
    "10-8s-3-8-10-8h-1v16h1z' fill='white'/%3E%3C/svg%3E"
)


def page_shell(title: str, content: str, refresh: bool = False) -> str:
    refresh_tag = '<meta http-equiv="refresh" content="3">' if refresh else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_tag}
  <title>{escape(title)}</title>
  <link rel="icon" href="{FAVICON}">
  <link rel="stylesheet" href="/assets/report.css?v={ASSET_VERSION}">
</head>
<body>
  {content}
</body>
</html>"""


def home_response(
    *,
    access_required: bool,
    error: str | None = None,
    username: str = "",
    status_code: int = status.HTTP_200_OK,
    headers: Mapping[str, str] | None = None,
) -> HTMLResponse:
    error_markup = (
        f'<p class="form-error" id="analysis-error" role="alert">{escape(error)}</p>'
        if error
        else ""
    )
    error_reference = ' aria-describedby="analysis-error"' if error else ""
    access_field = (
        f"""
      <div class="field-group">
        <label for="access_key">Access key</label>
        <input id="access_key" name="access_key" type="password" required
          autocomplete="current-password"{error_reference}>
        <p class="field-help">Use the DevDNA access key provided to your team.</p>
      </div>"""
        if access_required
        else ""
    )
    content = f"""
<main class="home-shell">
  <header class="home-nav">
    <div class="brand">DevDNA <span>Developer evidence</span></div>
    <a class="button button-secondary button-compact" href="/docs">API docs</a>
  </header>
  <section class="home-hero">
    <div class="home-intro">
      <p class="eyebrow">Evidence-first developer intelligence</p>
      <h1>See the work behind the profile.</h1>
      <p>DevDNA turns public repository files into explainable skill evidence and
        focused next steps.</p>
    </div>
    <form class="analysis-form" method="post" action="/analyses">
      <div class="form-heading">
        <h2>Analyze a developer</h2>
        <p>Start with a public GitHub account.</p>
      </div>
      {error_markup}
      <div class="field-group">
        <label for="github_username">GitHub username</label>
        <div class="username-input">
          <span aria-hidden="true">github.com/</span>
          <input id="github_username" name="github_username" value="{escape(username, quote=True)}"
            required maxlength="39" autocomplete="off" autocapitalize="none" spellcheck="false"
            placeholder="octocat"{error_reference}>
        </div>
        <p class="field-help">Public repositories only. No GitHub password is required.</p>
      </div>
      <div class="field-group">
        <label for="target_role">Target role</label>
        <select id="target_role" name="target_role">
          <option value="python_backend_developer">Python backend developer</option>
        </select>
      </div>
      {access_field}
      <button class="button button-primary form-submit" type="submit">Analyze profile</button>
    </form>
  </section>
  <section class="home-workflow" aria-labelledby="workflow-title">
    <h2 id="workflow-title">From GitHub to a useful decision</h2>
    <ol>
      <li>
        <strong>Inspect repositories</strong>
        <span>Read public source, tests, documentation, and delivery files.</span>
      </li>
      <li>
        <strong>Verify evidence</strong>
        <span>Match concrete artifacts to a role-specific engineering rubric.</span>
      </li>
      <li>
        <strong>Explain the result</strong>
        <span>Show strengths, gaps, sources, and prioritized recommendations.</span>
      </li>
    </ol>
  </section>
  <footer class="home-footer">
    <p>Built for developers and hiring teams who need explainable signals.</p>
  </footer>
</main>"""
    return HTMLResponse(
        page_shell("DevDNA evidence reports", content),
        status_code=status_code,
        headers=headers,
    )


def rate_limit_headers(response: Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower().startswith("x-ratelimit-") or name.lower() == "retry-after"
    }


def render_pending_page(username: str, analysis_id: str, analysis_status: str) -> str:
    content = f"""
<main class="pending-shell">
  <a class="brand" href="/" aria-label="DevDNA home">DevDNA <span>Developer evidence</span></a>
  <section class="pending-panel" aria-live="polite" aria-busy="true">
    <div class="pending-signal" aria-hidden="true"><span></span><span></span><span></span></div>
    <p class="eyebrow">Analysis {escape(analysis_status)}</p>
    <h1>Reading {escape(username)}’s work.</h1>
    <p>We are inspecting public project files and matching claims to direct evidence.</p>
    <div class="pending-actions">
      <a class="button button-primary"
        href="/reports/{escape(analysis_id, quote=True)}">Check again</a>
      <a class="button button-secondary"
        href="/v1/analyses/{escape(analysis_id, quote=True)}">View raw status</a>
    </div>
  </section>
</main>"""
    return page_shell(f"{username} | DevDNA report", content, refresh=True)


def render_sources(strength: ReportStrength) -> str:
    links = "".join(
        f"""<a class="source-link" href="{escape(source.url, quote=True)}"
          target="_blank" rel="noopener noreferrer">
          <span class="source-repository">{escape(source.repository)}</span>
          <strong>{escape(source.path)}</strong>
          <span class="source-open" aria-hidden="true">Open</span>
        </a>"""
        for source in strength.sources
    )
    return f'<div class="source-list" aria-label="Evidence sources">{links}</div>'


def render_requirement(
    requirement_key: str,
    strength: ReportStrength | None,
    gap: ReportGap | None,
    action: ReportAction | None,
) -> str:
    if strength is not None:
        return f"""
<li class="evidence-row verified">
  <div class="spine-marker" aria-hidden="true"></div>
  <article>
    <p class="row-state">Verified evidence</p>
    <h3>{escape(strength.title)}</h3>
    <p>{escape(strength.summary)}</p>
    {render_sources(strength)}
  </article>
</li>"""

    if gap is None or action is None:
        raise ValueError(f"incomplete report requirement: {requirement_key}")
    return f"""
<li class="evidence-row gap">
  <div class="spine-marker" aria-hidden="true"></div>
  <article>
    <p class="row-state">Evidence gap</p>
    <h3>{escape(gap.title)}</h3>
    <p>{escape(gap.explanation)}</p>
    <a class="row-action" href="#action-{escape(requirement_key, quote=True)}">
      Next: {escape(action.title)}
    </a>
  </article>
</li>"""


def render_action(action: ReportAction) -> str:
    needed = "".join(f"<li>{escape(item)}</li>" for item in action.evidence_needed)
    return f"""
<article class="action-row" id="action-{escape(action.requirement, quote=True)}">
  <div class="action-priority" aria-label="Priority {action.priority}">{action.priority}</div>
  <div>
    <p class="action-requirement">{escape(action.requirement.replace("_", " "))}</p>
    <h3>{escape(action.title)}</h3>
    <p>{escape(action.rationale)}</p>
    <ul class="needed-list">{needed}</ul>
  </div>
</article>"""


def render_report_page(
    username: str,
    analysis_id: str,
    report: ReportSnapshot,
) -> str:
    rubric = get_rubric(report.target_role)
    strengths = {item.requirement: item for item in report.strengths}
    gaps = {item.requirement: item for item in report.gaps}
    actions = {item.requirement: item for item in report.actions}
    evidence_rows = "".join(
        render_requirement(
            requirement.key,
            strengths.get(requirement.key),
            gaps.get(requirement.key),
            actions.get(requirement.key),
        )
        for requirement in rubric.requirements
    )
    action_rows = (
        "".join(render_action(action) for action in report.actions)
        if report.actions
        else '<p class="empty-note">Every version-1 requirement has source-backed evidence.</p>'
    )
    warning = (
        f"""<aside class="warning">
          <strong>Partial inspection</strong>
          <span>{escape(report.warning or "Some repository data was unavailable.")}</span>
        </aside>"""
        if report.collection_status == "partial"
        else ""
    )

    content = f"""
<header class="topbar">
  <a class="brand" href="/" aria-label="DevDNA home">DevDNA <span>Developer evidence</span></a>
  <a class="button button-secondary button-compact"
    href="/v1/analyses/{escape(analysis_id, quote=True)}/report">
    Open JSON
  </a>
</header>
<main class="report-shell">
  <section class="report-hero">
    <div class="hero-content">
      <p class="eyebrow">Python backend developer</p>
      <h1>Evidence over activity.</h1>
      <p class="hero-copy">
        A source-backed view of <strong>{escape(username)}</strong>: verified skills,
        evidence gaps, and the next useful work.
      </p>
    </div>
    <div class="coverage-block" aria-label="Rubric coverage">
      <div class="coverage-score">
        <span class="coverage-number">{report.requirements_met}</span>
        <span class="coverage-total">of {report.requirements_total}</span>
      </div>
      <div>
        <strong>{escape(report.alignment_label)}</strong>
        <small>requirements verified with direct file evidence</small>
      </div>
    </div>
  </section>
  {warning}
  <section class="evidence-section" aria-labelledby="evidence-title">
    <div class="section-heading">
      <h2 id="evidence-title">The evidence spine</h2>
      <p>Every verified statement links to the exact public file behind it.</p>
    </div>
    <ol class="evidence-spine">{evidence_rows}</ol>
  </section>
  <section class="actions-section" aria-labelledby="actions-title">
    <div class="section-heading">
      <h2 id="actions-title">Build next</h2>
      <p>Recommendations follow the role rubric, not popularity or trend signals.</p>
    </div>
    <div class="action-list">{action_rows}</div>
  </section>
  <footer>
    <p>Generated from public repository files.</p>
    <p>Commits, streaks, stars, and followers are not treated as engineering evidence.</p>
  </footer>
</main>"""
    return page_shell(f"{username} | DevDNA evidence report", content)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return home_response(access_required=bool(request.app.state.api_credentials))


@router.post("/analyses", response_class=HTMLResponse)
async def submit_analysis(request: Request, session: SessionDependency) -> Response:
    if request.headers.get("content-type", "").split(";", 1)[0] != (
        "application/x-www-form-urlencoded"
    ):
        return home_response(
            access_required=bool(request.app.state.api_credentials),
            error="The analysis form could not be read. Please submit it again.",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    try:
        fields = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return home_response(
            access_required=bool(request.app.state.api_credentials),
            error="The analysis form contains invalid text.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    username = fields.get("github_username", [""])[0].strip()
    target_role = fields.get("target_role", [""])[0]
    access_key = fields.get("access_key", [""])[0]
    policy_response = Response()
    authorization_header = f"Bearer {access_key}" if access_key else None
    try:
        await enforce_analysis_creation_access(request, policy_response, authorization_header)
    except HTTPException as error:
        return home_response(
            access_required=bool(request.app.state.api_credentials),
            error=str(error.detail),
            username=username,
            status_code=error.status_code,
            headers=error.headers,
        )

    try:
        payload = AnalysisCreate.model_validate(
            {"github_username": username, "target_role": target_role}
        )
    except ValidationError:
        return home_response(
            access_required=bool(request.app.state.api_credentials),
            error="Enter a valid GitHub username and select a supported role.",
            username=username,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            headers=rate_limit_headers(policy_response),
        )

    try:
        analysis = await start_analysis(payload, session, cast(Queue, request.app.state.queue))
    except HTTPException as error:
        return home_response(
            access_required=bool(request.app.state.api_credentials),
            error=str(error.detail),
            username=username,
            status_code=error.status_code,
            headers=rate_limit_headers(policy_response),
        )

    redirect = RedirectResponse(
        url=f"/reports/{analysis.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    for name, value in rate_limit_headers(policy_response).items():
        redirect.headers[name] = value
    return redirect


@router.get("/reports/{analysis_id}", response_class=HTMLResponse)
async def report_page(
    analysis_id: str,
    session: SessionDependency,
) -> HTMLResponse:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        return HTMLResponse(
            render_pending_page(
                analysis.github_username,
                analysis.id,
                analysis.status,
            ),
            status_code=status.HTTP_202_ACCEPTED,
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    return HTMLResponse(render_report_page(analysis.github_username, analysis.id, report))


def asset_directory() -> Path:
    return Path(__file__).with_name("web_assets")
