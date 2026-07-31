from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.database import get_session
from devdna.models import AnalysisRun
from devdna.rubrics import get_rubric
from devdna.schemas import ReportAction, ReportGap, ReportSnapshot, ReportStrength

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
async def home() -> HTMLResponse:
    content = """
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
      <a class="button button-primary" href="/docs">Start with the API</a>
    </div>
    <aside class="home-proof" aria-label="How DevDNA evaluates developers">
      <p class="proof-lead">No vanity metrics.</p>
      <dl>
        <div><dt>Claims</dt><dd>Linked to exact files</dd></div>
        <div><dt>Gaps</dt><dd>Marked as unverified</dd></div>
        <div><dt>Next steps</dt><dd>Ordered by role fit</dd></div>
      </dl>
    </aside>
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
    return HTMLResponse(page_shell("DevDNA evidence reports", content))


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
