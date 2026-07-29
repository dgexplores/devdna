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
ASSET_VERSION = "1"
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
  <a class="brand" href="/">DevDNA <span>/ evidence report</span></a>
  <section class="pending-panel" aria-live="polite">
    <div class="pending-mark" aria-hidden="true"></div>
    <p class="eyebrow">Analysis {escape(analysis_status)}</p>
    <h1>Reading {escape(username)}’s repositories.</h1>
    <p>DevDNA is collecting public project files and matching only verifiable evidence.</p>
    <a class="text-link" href="/v1/analyses/{escape(analysis_id, quote=True)}">
      View analysis data
    </a>
  </section>
</main>"""
    return page_shell(f"{username} · DevDNA report", content, refresh=True)


def render_sources(strength: ReportStrength) -> str:
    links = "".join(
        f"""<a class="source-link" href="{escape(source.url, quote=True)}"
          target="_blank" rel="noopener noreferrer">
          <span>{escape(source.repository)}</span>
          <strong>{escape(source.path)}</strong>
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
  <div class="spine-marker" aria-label="Verified">✓</div>
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
  <div class="spine-marker" aria-label="Evidence gap">→</div>
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
  <div class="action-priority">P{action.priority}</div>
  <div>
    <p class="eyebrow">{escape(action.requirement.replace("_", " "))}</p>
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
  <a class="brand" href="/">DevDNA <span>/ evidence report</span></a>
  <a class="data-link" href="/v1/analyses/{escape(analysis_id, quote=True)}/report">
    JSON report ↗
  </a>
</header>
<main class="report-shell">
  <section class="report-hero">
    <div>
      <p class="eyebrow">Python backend developer · {escape(report.rubric_version)}</p>
      <h1>Evidence, not activity.</h1>
      <p class="hero-copy">
        A repository-backed view of <strong>{escape(username)}</strong>—what is verified,
        what is not yet visible, and what to build next.
      </p>
    </div>
    <div class="coverage-block" aria-label="Rubric coverage">
      <span class="coverage-number">{report.requirements_met}/{report.requirements_total}</span>
      <strong>{escape(report.alignment_label)}</strong>
      <small>requirements with direct file evidence</small>
    </div>
  </section>
  {warning}
  <section class="evidence-section" aria-labelledby="evidence-title">
    <div class="section-heading">
      <p class="eyebrow">Requirement → proof</p>
      <h2 id="evidence-title">The evidence spine</h2>
      <p>Every verified statement opens the exact public file behind it.</p>
    </div>
    <ol class="evidence-spine">{evidence_rows}</ol>
  </section>
  <section class="actions-section" aria-labelledby="actions-title">
    <div class="section-heading">
      <p class="eyebrow">Prioritized roadmap</p>
      <h2 id="actions-title">What strengthens the profile next</h2>
      <p>Actions are ordered by the role rubric, not by popularity or trend signals.</p>
    </div>
    <div class="action-list">{action_rows}</div>
  </section>
  <footer>
    <p>Generated from public repository files by {escape(report.report_version)}.</p>
    <p>Commits, streaks, stars, and followers are not treated as engineering evidence.</p>
  </footer>
</main>"""
    return page_shell(f"{username} · DevDNA evidence report", content)


@router.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    content = """
<main class="pending-shell">
  <div class="brand">DevDNA <span>/ evidence report</span></div>
  <section class="pending-panel">
    <p class="eyebrow">Evidence-first developer intelligence</p>
    <h1>Open a finished analysis report.</h1>
    <p>Create an analysis through the API, then visit
      <code>/reports/&lt;analysis-id&gt;</code>.</p>
    <a class="text-link" href="/docs">Open API documentation</a>
  </section>
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
