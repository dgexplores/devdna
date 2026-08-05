import json
import re
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import parse_qs

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import ValidationError
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.analyses import analyses_for_owner, owner_requested_analysis, start_analysis
from devdna.cv import CvFileError, align_cv_to_evidence, extract_cv_text
from devdna.database import get_session
from devdna.learning import generate_learning_plan
from devdna.models import AnalysisRun, RecruiterBatch
from devdna.readme import generate_profile_readme
from devdna.recruiter import batch_response, create_batch
from devdna.rubrics import get_rubric
from devdna.schemas import (
    AnalysisCreate,
    CvAlignment,
    EvidenceSnapshot,
    LearningPlan,
    LearningRecommendation,
    ReadmeDraft,
    RecruiterBatchResponse,
    RecruiterCandidateResult,
    ReportAction,
    ReportGap,
    ReportSnapshot,
    ReportStrength,
)
from devdna.security import enforce_analysis_creation_access, enforce_fixed_window
from devdna.web_sessions import SESSION_COOKIE, create_web_session, verify_web_session

router = APIRouter(tags=["web"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ASSET_VERSION = "3"
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


def topbar_nav(brand_suffix: str, *, home_url: str = "/") -> str:
    return f"""<header class="topbar">
  <a class="brand" href="{escape(home_url, quote=True)}" aria-label="DevDNA home">
    <span class="brand-mark">DNA</span>DevDNA <span>{escape(brand_suffix)}</span>
  </a>
  <nav class="home-links" aria-label="Primary navigation">
    <a href="/app">Dashboard</a>
    <a href="/history">History</a>
    <a href="/recruiter">Recruiter</a>
  </nav>
</header>"""


def auth_script(clerk_key: str) -> str:
    """Load Clerk and render the embedded <SignIn/> component, then exchange the
    resulting session token for a DevDNA web session cookie."""
    if not clerk_key:
        return "<script>window.__DEVDNA_AUTH__ = { key: null };</script>"
    safe_key = json.dumps(clerk_key)
    return f"""<script>
  window.__DEVDNA_AUTH__ = {{ key: {safe_key} }};
  (function () {{
    var key = window.__DEVDNA_AUTH__.key;
    if (!key) return;
    var script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/@clerk/clerk-js@latest/dist/clerk.browser.js";
    script.setAttribute("data-clerk-publishable-key", key);
    script.async = true;
    script.onload = async function () {{
      if (!window.Clerk) return;
      var clerk = window.Clerk;
      try {{
        await clerk.load({{ afterSignInUrl: "/app", afterSignUpUrl: "/app" }});
      }} catch (e) {{
        console.error("Clerk load failed", e);
        return;
      }}
      var exchange = function (token) {{
        return fetch("/auth/clerk", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ token: token }}),
        }});
      }};
      var redirectToApp = function () {{
        if (window.location.pathname !== "/app") window.location.href = "/app";
      }};
      if (clerk.user) {{
        try {{
          var token = await clerk.session.getToken();
          await exchange(token);
        }} finally {{
          redirectToApp();
        }}
        return;
      }}
      var host = document.getElementById("clerk-sign-in");
      if (host && typeof clerk.mountSignIn === "function") {{
        try {{
          clerk.mountSignIn(host, {{
            withSignUp: true,
            fallbackRedirectUrl: "/app",
            afterSignInUrl: "/app",
            afterSignUpUrl: "/app",
            routing: "hash",
            appearance: {{
              baseTheme: null,
              variables: {{
                colorPrimary: "#58a6ff",
                colorBackground: "#11151c",
                colorText: "#e6edf3",
                colorTextSecondary: "#9aa7b7",
                colorInputBackground: "#0a0c10",
                colorInputText: "#e6edf3",
                borderRadius: "8px",
                fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                fontFamilyButtons: "inherit"
              }}
            }}
          }});
        }} catch (e) {{
          console.error("Clerk mountSignIn failed", e);
          var note = document.createElement("p");
          note.className = "form-error";
          note.textContent = "Sign-in is unavailable. Please try again.";
          host.appendChild(note);
        }}
      }}
      clerk.addListener(function (payload) {{
        if (!payload.signedIn) return;
        clerk.session.getToken().then(function (token) {{
          return exchange(token);
        }}).then(redirectToApp);
      }});
    }};
    document.head.appendChild(script);
  }})();
</script>"""


def home_response(
    *,
    access_required: bool,
    error: str | None = None,
    username: str = "",
    status_code: int = status.HTTP_200_OK,
    headers: Mapping[str, str] | None = None,
    clerk_key: str = "",
    authenticated: bool = False,
) -> HTMLResponse:
    error_markup = f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    content = f"""
<main class="home-shell">
  <header class="home-nav">
    <div class="home-nav-inner home-nav">
      <a class="brand" href="/" aria-label="DevDNA home">
        <span class="brand-mark">DNA</span>DevDNA <span>developer evidence</span>
      </a>
      <nav class="home-links" aria-label="Primary navigation">
        <a href="/history">History</a>
        <a href="/recruiter">Recruiter</a>
        <a href="/docs">API docs</a>
      </nav>
    </div>
  </header>
  <section class="home-hero">
    <div class="home-intro">
      <p class="eyebrow">Evidence-first developer intelligence</p>
      <h1>Turn your GitHub into a hiring signal.</h1>
      <p>DevDNA reads your public repositories and tells you exactly what they
        prove about your skills — and what they still lack for the role you want.</p>
      <div class="hero-cta">
        <a class="button button-primary" href="/app">Get your DevDNA report</a>
        <a class="button button-secondary" href="/docs">Read the API docs</a>
      </div>
    </div>
    <aside class="auth-panel" aria-label="Sign in">
      <div class="auth-head">
        <p class="eyebrow">Sign in to continue</p>
        <h2 class="auth-title">Your profile, decoded.</h2>
        <p class="auth-sub">Sign in with Google, GitHub, or email to unlock your
          analysis dashboard.</p>
      </div>
      {error_markup}
      <div id="clerk-sign-in" class="clerk-signin" aria-label="Clerk sign in"></div>
      <p class="auth-note">Public repositories only. No GitHub password required.</p>
    </aside>
  </section>
  <section class="home-features" aria-label="What DevDNA does">
    <article class="feature-card">
      <div class="feature-icon" aria-hidden="true">01</div>
      <h3>Inspect repositories</h3>
      <p>Read public source, tests, documentation, and delivery files.</p>
    </article>
    <article class="feature-card">
      <div class="feature-icon" aria-hidden="true">02</div>
      <h3>Verify evidence</h3>
      <p>Match concrete artifacts to a role-specific engineering rubric.</p>
    </article>
    <article class="feature-card">
      <div class="feature-icon" aria-hidden="true">03</div>
      <h3>Explain the result</h3>
      <p>Show strengths, gaps, sources, and prioritized recommendations.</p>
    </article>
  </section>
  <section class="home-workflow" aria-labelledby="workflow-title">
    <div class="section-heading">
      <h2 id="workflow-title">From GitHub to a useful decision</h2>
      <p>Every claim links to the exact public file that backs it up.</p>
    </div>
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
    <p>Commits, streaks, stars, and followers are not treated as engineering evidence.</p>
  </footer>
</main>
{auth_script(clerk_key)}"""
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


def dashboard_response(
    *,
    username: str = "",
    action: str = "",
    error: str | None = None,
    clerk_key: str = "",
    status_code: int = status.HTTP_200_OK,
    authenticated: bool = False,
) -> HTMLResponse:
    error_markup = (
        f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    )
    actions = {
        "profile": "Analyze my profile",
        "readme": "Improve my README",
        "role": "See where I stand for a role",
        "gaps": "What my GitHub is lacking",
    }
    action_options = "".join(
        f'<label class="action-option"><input type="radio" name="action" value="{key}"'
        f'{" checked" if key == action else ""}><span>{label}</span></label>'
        for key, label in actions.items()
    )
    sign_out = (
        """
      <form method="post" action="/session/logout" class="inline-form">
        <button class="text-button" type="submit">Sign out</button>
      </form>"""
        if authenticated
        else ""
    )
    user_badge = (
        '<span class="app-user"><span class="dot" aria-hidden="true"></span>Signed in</span>'
        if authenticated
        else ""
    )
    content = f"""
<main class="home-shell">
  <header class="home-nav">
    <div class="home-nav-inner home-nav">
      <a class="brand" href="/" aria-label="DevDNA home">
        <span class="brand-mark">DNA</span>DevDNA <span>developer evidence</span>
      </a>
      <nav class="home-links" aria-label="Primary navigation">
        <a href="/history">History</a>
        <a href="/recruiter">Recruiter</a>
        {sign_out}
      </nav>
    </div>
  </header>
  <section class="app-hero">
    <div class="app-intro">
      <p class="eyebrow">Your analysis dashboard</p>
      {user_badge}
      <h1>What should we do with your GitHub?</h1>
      <p>Paste a GitHub username and pick what you want to know.</p>
    </div>
    <form class="analysis-form" method="post" action="/app/analyze">
      <div class="form-heading">
        <h2>Choose an action</h2>
        <p>Start with a public GitHub account.</p>
      </div>
      {error_markup}
      <div class="field-group">
        <label for="github_username">GitHub username</label>
        <div class="username-input">
          <span aria-hidden="true">github.com/</span>
          <input id="github_username" name="github_username" value="{escape(username, quote=True)}"
            required maxlength="39" autocomplete="off" autocapitalize="none" spellcheck="false"
            placeholder="octocat">
        </div>
      </div>
      <div class="field-group">
        <label>What do you want to do?</label>
        <div class="action-grid">{action_options}</div>
      </div>
      <button class="button button-primary form-submit" type="submit">Run analysis</button>
    </form>
  </section>
</main>
{auth_script(clerk_key)}"""
    return HTMLResponse(
        page_shell("DevDNA dashboard", content),
        status_code=status_code,
    )


def render_pending_page(username: str, analysis_id: str, analysis_status: str) -> str:
    content = f"""
{topbar_nav("Developer evidence")}
<main class="pending-shell">
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


def render_readme_page(username: str, analysis_id: str, draft: ReadmeDraft) -> str:
    repository_items = "".join(
        f'<li><a href="{escape(repository.url, quote=True)}" target="_blank" '
        f'rel="noopener noreferrer">{escape(repository.name)}</a></li>'
        for repository in draft.repositories[:4]
    )
    repository_note = (
        f'<ul class="readme-repositories">{repository_items}</ul>'
        if repository_items
        else '<p class="empty-note">No repository has verified role evidence yet.</p>'
    )
    content = f"""
{topbar_nav("README studio")}
<main class="readme-shell">
  <section class="readme-hero">
    <div>
      <p class="eyebrow">Evidence-constrained draft</p>
      <h1>A stronger profile, without invented claims.</h1>
      <p>Built from {escape(username)}’s verified project evidence and current improvement plan.</p>
    </div>
    <div class="readme-actions">
      <a class="button button-secondary"
        href="/reports/{escape(analysis_id, quote=True)}">
        Back to report
      </a>
      <a class="button button-primary" href="/reports/{escape(analysis_id, quote=True)}/readme.md">
        Download Markdown
      </a>
      <a class="button button-secondary"
        href="/v1/analyses/{escape(analysis_id, quote=True)}/readme">
        Open JSON
      </a>
    </div>
  </section>
  <section class="readme-workspace" aria-labelledby="draft-title">
    <div class="readme-guidance">
      <h2 id="draft-title">Your draft</h2>
      <p>Review the wording, add contact details, then place it in your profile repository.</p>
      <h3>Featured evidence</h3>
      {repository_note}
    </div>
    <textarea class="markdown-draft" readonly spellcheck="false"
      aria-label="Generated profile README Markdown">{escape(draft.markdown)}</textarea>
  </section>
  <section class="cv-panel" aria-labelledby="cv-title">
    <div>
      <p class="eyebrow">Optional CV check</p>
      <h2 id="cv-title">Compare your CV with public evidence.</h2>
      <p>Upload a PDF or DOCX to see which stated skills this GitHub analysis can verify.
        Your file is processed in memory and is not saved.</p>
    </div>
    <form class="cv-form" method="post"
      action="/reports/{escape(analysis_id, quote=True)}/cv-align"
      enctype="multipart/form-data">
      <div class="field-group">
        <label for="cv_file">CV file</label>
        <input id="cv_file" name="file" type="file" accept=".pdf,.docx" required>
        <p class="field-help">PDF or DOCX, up to 2 MB. Image-only PDFs are not supported.</p>
      </div>
      <button class="button button-primary" type="submit">Check CV evidence</button>
    </form>
  </section>
  <footer>
    <p>Every technical claim comes from the saved DevDNA evidence report.</p>
    <p>Review personal wording before publishing.</p>
  </footer>
</main>"""
    return page_shell(f"{username} | DevDNA README draft", content)


def render_cv_skill_list(alignment: CvAlignment, *, verified: bool) -> str:
    expected_status = "verified" if verified else "self_reported_unverified"
    entries = []
    for skill in alignment.skills:
        if skill.status != expected_status:
            continue
        sources = "".join(
            f'<li><a href="{escape(source.url, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{escape(source.repository)} / '
            f"{escape(source.path)}</a></li>"
            for source in skill.evidence_sources
        )
        source_list = f'<ul class="cv-source-list">{sources}</ul>' if sources else ""
        entries.append(
            f'<li class="cv-skill"><strong>{escape(skill.skill)}</strong>{source_list}</li>'
        )
    if not entries:
        message = (
            "No matching public evidence found." if verified else "No CV-only skills detected."
        )
        return f'<p class="empty-note">{message}</p>'
    return f'<ul class="cv-skill-list">{"".join(entries)}</ul>'


def render_cv_alignment_page(
    username: str,
    analysis_id: str,
    alignment: CvAlignment,
) -> str:
    guidance = "".join(f"<li>{escape(item)}</li>" for item in alignment.guidance)
    content = f"""
{topbar_nav("CV evidence check")}
<main class="cv-alignment-shell">
  <section class="cv-result-hero">
    <p class="eyebrow">{escape(alignment.source_filename)}</p>
    <h1>CV claims, checked against {escape(username)}’s GitHub evidence.</h1>
    <p>{escape(alignment.suggested_summary)}</p>
    <div class="readme-actions">
      <a class="button button-secondary"
        href="/reports/{escape(analysis_id, quote=True)}/readme">Back to README studio</a>
    </div>
  </section>
  <section class="cv-groups" aria-label="CV skill alignment">
    <article class="cv-group verified">
      <p class="row-state">Verified in GitHub</p>
      <h2>Supported claims</h2>
      <p>These skills have direct repository evidence in the saved analysis.</p>
      {render_cv_skill_list(alignment, verified=True)}
    </article>
    <article class="cv-group unverified">
      <p class="row-state">CV only — not verified</p>
      <h2>Evidence still needed</h2>
      <p>These items cannot be presented as verified until public repository evidence exists.</p>
      {render_cv_skill_list(alignment, verified=False)}
    </article>
  </section>
  <section class="cv-guidance" aria-labelledby="guidance-title">
    <h2 id="guidance-title">What to do next</h2>
    <ul>{guidance}</ul>
  </section>
</main>"""
    return page_shell(f"{username} | DevDNA CV alignment", content)


def render_learning_recommendation(item: LearningRecommendation) -> str:
    outcomes = "".join(f"<li>{escape(outcome)}</li>" for outcome in item.learning_outcomes)
    evidence = "".join(f"<li>{escape(entry)}</li>" for entry in item.evidence_to_publish)
    source = (
        f"""<a class="learning-source" href="{escape(item.source_url or "", quote=True)}"
          target="_blank" rel="noopener noreferrer">
          {escape(item.source_label or "Source")} | reviewed {escape(item.reviewed_on or "")}
        </a>"""
        if item.source_url
        else ""
    )
    return f"""
<article class="learning-item {escape(item.kind, quote=True)}">
  <div class="learning-priority" aria-label="Priority {item.priority}">{item.priority}</div>
  <div>
    <p class="action-requirement">{escape(item.kind.replace("_", " "))}</p>
    <h3>{escape(item.title)}</h3>
    <p>{escape(item.rationale)}</p>
    <h4>Learn</h4>
    <ul>{outcomes}</ul>
    <h4>Build</h4>
    <p>{escape(item.project_brief)}</p>
    <h4>Publish as evidence</h4>
    <ul>{evidence}</ul>
    {source}
  </div>
</article>"""


def render_learning_page(username: str, analysis_id: str, plan: LearningPlan) -> str:
    role_items = "".join(
        render_learning_recommendation(item)
        for item in plan.recommendations
        if item.kind == "role_gap"
    )
    market_items = "".join(
        render_learning_recommendation(item)
        for item in plan.recommendations
        if item.kind == "market_signal"
    )
    role_content = role_items or (
        '<p class="empty-note">The current role rubric has direct evidence '
        "for every requirement.</p>"
    )
    content = f"""
{topbar_nav("Learning plan")}
<main class="learning-shell">
  <section class="learning-hero">
    <p class="eyebrow">Python backend developer</p>
    <h1>Learn what your portfolio cannot prove yet.</h1>
    <p>A practical sequence for {escape(username)}, grounded in role gaps and
      dated market signals.</p>
    <div class="readme-actions">
      <a class="button button-secondary"
        href="/reports/{escape(analysis_id, quote=True)}">Back to report</a>
    </div>
  </section>
  <section class="learning-section" aria-labelledby="role-learning-title">
    <div class="section-heading">
      <h2 id="role-learning-title">Close the role gaps</h2>
      <p>Complete these in order. Each project ends with reviewable GitHub evidence.</p>
    </div>
    <div class="learning-list">{role_content}</div>
  </section>
  <section class="market-section" aria-labelledby="market-title">
    <div class="section-heading">
      <h2 id="market-title">Explore what is growing</h2>
      <p>Market signals are dated and sourced. They never change your verified skill evidence.</p>
    </div>
    <div class="learning-list">{market_items}</div>
  </section>
  <footer>
    <p>Role gaps come from the saved evidence report.</p>
    <p>Market signals require periodic review.</p>
  </footer>
</main>"""
    return page_shell(f"{username} | DevDNA learning plan", content)


def render_history_page(analyses: list[AnalysisRun], authenticated: bool) -> str:
    rows = "".join(
        f"""
<li class="history-row">
  <a href="/reports/{escape(analysis.id, quote=True)}">
    <div>
      <strong>{escape(analysis.github_username)}</strong>
      <span>Python backend developer</span>
    </div>
    <div class="history-meta">
      <span class="status-label {escape(analysis.status, quote=True)}">
        {escape(analysis.status)}
      </span>
      <time datetime="{analysis.created_at.isoformat()}">
        {analysis.created_at.strftime("%d %b %Y")}
      </time>
    </div>
  </a>
</li>"""
        for analysis in analyses
    )
    history_content = (
        f'<ol class="history-list">{rows}</ol>'
        if rows
        else """
<div class="history-empty">
  <h2>No analyses yet</h2>
  <p>Start with a public GitHub username. Finished reports will appear here.</p>
  <a class="button button-primary" href="/">Analyze a profile</a>
</div>"""
    )
    sign_out = (
        """
    <form method="post" action="/session/logout">
      <button class="button button-secondary button-compact" type="submit">Sign out</button>
    </form>"""
        if authenticated
        else '<a class="button button-secondary button-compact" href="/">New analysis</a>'
    )
    content = f"""
<main class="history-shell">
  <header class="topbar">
    <a class="brand" href="/" aria-label="DevDNA home">
      <span class="brand-mark">DNA</span>DevDNA <span>Analysis history</span>
    </a>
    <div class="topbar-actions">
      <a class="nav-link" href="/app">Dashboard</a>
      {sign_out}
    </div>
  </header>
  <section class="history-hero">
    <p class="eyebrow">Saved requests</p>
    <h1>Developer analysis history.</h1>
    <p>Return to progress, reports, README drafts, and learning plans.</p>
  </section>
  <section class="history-content" aria-label="Analysis history">{history_content}</section>
</main>"""
    return page_shell("Analysis history | DevDNA", content)


def render_recruiter_home(error: str | None = None) -> str:
    error_markup = f'<p class="form-error" role="alert">{escape(error)}</p>' if error else ""
    content = f"""
{topbar_nav("Recruiter workspace")}
<main class="recruiter-shell">
  <section class="recruiter-hero">
    <div>
      <p class="eyebrow">Evidence comparison</p>
      <h1>Review a candidate list with the same rubric.</h1>
      <p>Upload public GitHub usernames. DevDNA compares reviewable engineering evidence and
        leaves the hiring decision to people.</p>
    </div>
    <form class="analysis-form" method="post" action="/recruiter/batches"
      enctype="multipart/form-data">
      <div class="form-heading">
        <h2>Create a batch</h2>
        <p>Up to 50 candidates per CSV or DOCX file.</p>
      </div>
      {error_markup}
      <div class="field-group">
        <label for="candidate_file">Candidate file</label>
        <input id="candidate_file" name="file" type="file" accept=".csv,.docx" required>
        <p class="field-help">Use a github_username column or GitHub profile links.</p>
      </div>
      <div class="field-group">
        <label for="recruiter_role">Target role</label>
        <select id="recruiter_role" name="target_role">
          <option value="python_backend_developer">Python backend developer</option>
        </select>
      </div>
      <button class="button button-primary form-submit" type="submit">Analyze candidates</button>
    </form>
  </section>
  <footer>
    <p>No protected traits are inferred. Coverage is not an autonomous hiring score.</p>
  </footer>
</main>"""
    return page_shell("Recruiter workspace | DevDNA", content)


def render_candidate(candidate: RecruiterCandidateResult) -> str:
    coverage = (
        f"{candidate.requirements_met} of {candidate.requirements_total}"
        if candidate.requirements_met is not None
        else "Analyzing"
    )
    return f"""
<article class="candidate-row">
  <div class="candidate-rank">{candidate.rank if candidate.rank is not None else "..."}</div>
  <div class="candidate-main">
    <div class="candidate-heading">
      <div><h3>{escape(candidate.github_username)}</h3><span>{escape(candidate.status)}</span></div>
      <strong>{coverage}</strong>
    </div>
    <p>{escape(candidate.alignment_label or "Repository analysis is still in progress.")}</p>
    <div class="candidate-evidence">
      <div><h4>Verified</h4><p>{escape(", ".join(candidate.strengths) or "Pending")}</p></div>
      <div><h4>Not verified</h4><p>{escape(", ".join(candidate.gaps) or "Pending")}</p></div>
    </div>
    <a class="row-action" href="/reports/{escape(candidate.analysis_id, quote=True)}">
      Open evidence report
    </a>
  </div>
</article>"""


def render_recruiter_batch(batch: RecruiterBatchResponse) -> str:
    pending = any(item.status in {"queued", "running"} for item in batch.candidates)
    cards = "".join(render_candidate(item) for item in batch.candidates)
    content = f"""
{topbar_nav("Candidate comparison")}
<main class="candidate-shell">
  <section class="candidate-hero">
    <p class="eyebrow">Python backend developer</p>
    <h1>Evidence comparison.</h1>
    <p>{len(batch.candidates)} candidates from {escape(batch.source_filename)}. Ranked only by
      verified coverage of this role rubric.</p>
    <div class="readme-actions">
      <a class="button button-secondary" href="/recruiter">New batch</a>
    </div>
  </section>
  <aside class="human-review-note">
    <strong>Human review required</strong>
    <span>Coverage helps order technical review. It must not automatically accept or reject
      anyone.</span>
  </aside>
  <section class="candidate-list" aria-label="Candidate comparison">{cards}</section>
</main>"""
    return page_shell("Candidate comparison | DevDNA", content, refresh=pending)


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
{topbar_nav("Developer evidence")}
<main class="report-shell">
  <section class="report-hero">
    <div class="hero-content">
      <p class="eyebrow">Python backend developer</p>
      <h1>Evidence over activity.</h1>
      <p class="hero-copy">
        A source-backed view of <strong>{escape(username)}</strong>: verified skills,
        evidence gaps, and the next useful work.
      </p>
      <div class="readme-actions">
        <a class="button button-secondary"
          href="/v1/analyses/{escape(analysis_id, quote=True)}/report">Open JSON</a>
      </div>
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
  <nav class="report-tools" aria-label="Developer tools">
    <a href="/reports/{escape(analysis_id, quote=True)}/readme">
      <strong>Profile README</strong>
      <span>Create a source-backed Markdown draft</span>
    </a>
    <a href="/reports/{escape(analysis_id, quote=True)}/learning">
      <strong>Learning plan</strong>
      <span>Turn evidence gaps into portfolio work</span>
    </a>
  </nav>
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
    return home_response(
        access_required=bool(request.app.state.api_credentials),
        clerk_key=request.app.state.settings.clerk_publishable_key,
    )


@router.post("/auth/clerk", response_class=HTMLResponse)
async def clerk_auth(request: Request) -> Response:
    """Exchange a Clerk session token for a DevDNA web session cookie."""
    from devdna.clerk import verify_clerk_token

    try:
        body = await request.body()
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    claims = verify_clerk_token(token, request.app.state.settings)
    if claims is None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    clerk_sub = claims.get("sub", "user")
    safe_client = re.sub(r"[^a-zA-Z0-9_-]", "", clerk_sub)[:48] or "clerk"
    max_age = request.app.state.settings.web_session_hours * 3600
    response = RedirectResponse(url="/app", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE,
        create_web_session(safe_client, request.app.state.web_session_secret, max_age),
        max_age=max_age,
        httponly=True,
        secure=request.app.state.settings.environment in {"staging", "production"},
        samesite="lax",
        path="/",
    )
    return response


@router.get("/app", response_class=HTMLResponse)
async def app_dashboard(request: Request) -> HTMLResponse:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    return dashboard_response(
        clerk_key=request.app.state.settings.clerk_publishable_key,
        authenticated=owner_id is not None,
    )


@router.post("/app/analyze", response_class=HTMLResponse)
async def app_analyze(request: Request, session: SessionDependency) -> Response:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    authenticated = owner_id is not None
    if request.headers.get("content-type", "").split(";", 1)[0] != (
        "application/x-www-form-urlencoded"
    ):
        return dashboard_response(
            error="The form could not be read. Please submit it again.",
            clerk_key=request.app.state.settings.clerk_publishable_key,
            authenticated=authenticated,
        )
    try:
        fields = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return dashboard_response(
            error="The form contains invalid text.",
            clerk_key=request.app.state.settings.clerk_publishable_key,
            authenticated=authenticated,
        )

    username = fields.get("github_username", [""])[0].strip()
    action = fields.get("action", [""])[0]
    if owner_id is None:
        return dashboard_response(
            username=username,
            action=action,
            error="Sign in with Clerk before starting an analysis.",
            clerk_key=request.app.state.settings.clerk_publishable_key,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.state.api_client_id = owner_id
    policy_response = Response()
    current, ttl = await enforce_fixed_window(
        request,
        policy_response,
        f"devdna:rate:analysis:client:{owner_id}",
        request.app.state.settings.analysis_rate_limit,
        request.app.state.settings.analysis_rate_window_seconds,
    )
    if current > request.app.state.settings.analysis_rate_limit:
        return dashboard_response(
            username=username,
            action=action,
            error="Analysis request limit exceeded. Please try again later.",
            clerk_key=request.app.state.settings.clerk_publishable_key,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            authenticated=authenticated,
        )

    try:
        payload = AnalysisCreate.model_validate(
            {"github_username": username, "target_role": "python_backend_developer"}
        )
    except ValidationError:
        return dashboard_response(
            username=username,
            action=action,
            error="Enter a valid GitHub username.",
            clerk_key=request.app.state.settings.clerk_publishable_key,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            authenticated=authenticated,
        )

    try:
        owner_id = request.state.api_client_id or "public"
        analysis = await start_analysis(
            payload,
            session,
            cast(Queue, request.app.state.queue),
            owner_id,
        )
    except HTTPException as error:
        return dashboard_response(
            username=username,
            action=action,
            error=str(error.detail),
            clerk_key=request.app.state.settings.clerk_publishable_key,
            authenticated=authenticated,
        )

    target = {
        "readme": "readme",
        "role": "learning",
        "gaps": "",
    }.get(action, "")
    redirect = RedirectResponse(
        url=f"/reports/{analysis.id}" + (f"/{target}" if target else ""),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    for name, value in rate_limit_headers(policy_response).items():
        redirect.headers[name] = value
    client_id = request.state.api_client_id
    if client_id:
        max_age = request.app.state.settings.web_session_hours * 3600
        redirect.set_cookie(
            SESSION_COOKIE,
            create_web_session(client_id, request.app.state.web_session_secret, max_age),
            max_age=max_age,
            httponly=True,
            secure=request.app.state.settings.environment in {"staging", "production"},
            samesite="lax",
            path="/",
        )
    return redirect


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
        owner_id = request.state.api_client_id or "public"
        analysis = await start_analysis(
            payload,
            session,
            cast(Queue, request.app.state.queue),
            owner_id,
        )
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
    client_id = request.state.api_client_id
    if client_id:
        max_age = request.app.state.settings.web_session_hours * 3600
        redirect.set_cookie(
            SESSION_COOKIE,
            create_web_session(client_id, request.app.state.web_session_secret, max_age),
            max_age=max_age,
            httponly=True,
            secure=request.app.state.settings.environment in {"staging", "production"},
            samesite="lax",
            path="/",
        )
    return redirect


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, session: SessionDependency) -> HTMLResponse:
    credentials_configured = bool(request.app.state.api_credentials)
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    if credentials_configured and owner_id is None:
        return home_response(
            access_required=True,
            error="Enter your access key and start an analysis to open private history.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    history = await analyses_for_owner(session, owner_id or "public", 50)
    return HTMLResponse(render_history_page(history, authenticated=owner_id is not None))


@router.post("/session/logout", response_class=HTMLResponse)
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/recruiter", response_class=HTMLResponse)
async def recruiter_home(request: Request) -> HTMLResponse:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    if request.app.state.api_credentials and owner_id is None:
        return home_response(
            access_required=True,
            error="Start an analysis with your access key before opening recruiter tools.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return HTMLResponse(render_recruiter_home())


@router.post("/recruiter/batches", response_class=HTMLResponse)
async def submit_recruiter_batch(
    request: Request,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    target_role: Annotated[str, Form()] = "python_backend_developer",
) -> Response:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    if request.app.state.api_credentials and owner_id is None:
        return home_response(
            access_required=True,
            error="Your recruiter session is missing or expired.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    settings = request.app.state.settings
    policy_response = Response()
    try:
        current, ttl = await enforce_fixed_window(
            request,
            policy_response,
            f"devdna:rate:recruiter:{owner_id or 'public'}",
            settings.recruiter_batch_rate_limit,
            settings.recruiter_batch_rate_window_seconds,
        )
    except HTTPException as error:
        return HTMLResponse(
            render_recruiter_home(str(error.detail)),
            status_code=error.status_code,
        )
    if current > settings.recruiter_batch_rate_limit:
        return HTMLResponse(
            render_recruiter_home(f"Recruiter batch limit reached. Try again in {ttl} seconds."),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers=rate_limit_headers(policy_response),
        )
    content = await file.read(settings.recruiter_upload_max_bytes + 1)
    if len(content) > settings.recruiter_upload_max_bytes:
        return HTMLResponse(
            render_recruiter_home("Recruiter upload is too large."),
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    try:
        batch = await create_batch(
            owner_id or "public",
            file.filename or "",
            content,
            target_role,
            session,
            cast(Queue, request.app.state.queue),
            settings.recruiter_batch_max_candidates,
        )
    except HTTPException as error:
        return HTMLResponse(
            render_recruiter_home(str(error.detail)),
            status_code=error.status_code,
        )
    redirect = RedirectResponse(
        url=f"/recruiter/batches/{batch.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    for name, value in rate_limit_headers(policy_response).items():
        redirect.headers[name] = value
    return redirect


@router.get("/recruiter/batches/{batch_id}", response_class=HTMLResponse)
async def recruiter_batch_page(
    batch_id: str,
    request: Request,
    session: SessionDependency,
) -> HTMLResponse:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    resolved_owner = owner_id or ("public" if not request.app.state.api_credentials else None)
    batch = await session.get(RecruiterBatch, batch_id)
    if batch is None or resolved_owner is None or batch.owner_id != resolved_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    result = await batch_response(batch, session)
    return HTMLResponse(render_recruiter_batch(result))


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


@router.get("/reports/{analysis_id}/readme", response_class=HTMLResponse)
async def readme_page(analysis_id: str, session: SessionDependency) -> HTMLResponse:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="README draft is not ready",
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    draft = generate_profile_readme(analysis.github_username, report)
    return HTMLResponse(render_readme_page(analysis.github_username, analysis.id, draft))


@router.get("/reports/{analysis_id}/readme.md", response_class=PlainTextResponse)
async def download_readme(analysis_id: str, session: SessionDependency) -> PlainTextResponse:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="README draft is not ready",
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    draft = generate_profile_readme(analysis.github_username, report)
    return PlainTextResponse(
        draft.markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="README.md"'},
    )


@router.post("/reports/{analysis_id}/cv-align", response_class=HTMLResponse)
async def cv_alignment_page(
    analysis_id: str,
    request: Request,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> HTMLResponse:
    owner_id = verify_web_session(
        request.cookies.get(SESSION_COOKIE),
        request.app.state.web_session_secret,
    )
    resolved_owner = owner_id or ("public" if not request.app.state.api_credentials else None)
    analysis = await session.get(AnalysisRun, analysis_id)
    if (
        analysis is None
        or resolved_owner is None
        or not await owner_requested_analysis(session, resolved_owner, analysis_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.evidence_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CV alignment is not ready",
        )

    settings = request.app.state.settings
    content = await file.read(settings.cv_upload_max_bytes + 1)
    if len(content) > settings.cv_upload_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="CV upload is too large",
        )
    try:
        cv_text = extract_cv_text(
            file.filename or "",
            content,
            max_pages=settings.cv_max_pages,
            max_characters=settings.cv_max_characters,
        )
    except CvFileError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    alignment = align_cv_to_evidence(
        analysis.github_username,
        file.filename or "",
        cv_text,
        EvidenceSnapshot.model_validate(analysis.evidence_snapshot),
    )
    return HTMLResponse(render_cv_alignment_page(analysis.github_username, analysis.id, alignment))


@router.get("/reports/{analysis_id}/learning", response_class=HTMLResponse)
async def learning_page(analysis_id: str, session: SessionDependency) -> HTMLResponse:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Learning plan is not ready",
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    plan = generate_learning_plan(report)
    return HTMLResponse(render_learning_page(analysis.github_username, analysis.id, plan))


def asset_directory() -> Path:
    return Path(__file__).with_name("web_assets")
