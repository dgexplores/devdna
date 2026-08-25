import asyncio
from pathlib import Path

from conftest import create_test_client
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.database import Base
from devdna.jd import (
    JD_SKILL_RULES,
    align_jd_to_evidence,
    capability_highlights_from_keys,
    validate_jd_text,
)
from devdna.models import AnalysisRun
from devdna.reports import generate_report
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource


def _evidence() -> EvidenceSnapshot:
    def item(key: str, repo: str = "octocat/backend") -> EvidenceItem:
        return EvidenceItem(
            key=key,
            category="test",
            claim=f"{key} present",
            repository=repo,
            sources=[
                EvidenceSource(
                    repository=repo,
                    path="pyproject.toml",
                    url=f"https://github.com/{repo}/blob/main/pyproject.toml",
                )
            ],
        )

    return EvidenceSnapshot(
        schema_version="1",
        analyzer_version="test",
        target_role="python_backend_developer",
        rubric_version="python_backend_developer:v1",
        repositories_analyzed=1,
        items=[
            item("python.project"),
            item("api.framework.fastapi"),
            item("delivery.container"),
        ],
    )


JD_TEXT = (
    "Requirements: strong Python skills, 3+ years building REST APIs. "
    "Experience with FastAPI and PostgreSQL required. CI/CD pipelines and Docker experience "
    "preferred. React and TypeScript are a plus."
)


def test_validate_jd_text_bounds() -> None:
    assert validate_jd_text("  " + JD_TEXT + "  ", max_characters=20_000) == JD_TEXT
    try:
        validate_jd_text("short", max_characters=20_000)
    except ValueError as error:
        assert "meaningful snippet" in str(error)
    else:
        raise AssertionError("short text must be rejected")
    try:
        validate_jd_text("x" * 21_000, max_characters=20_000)
    except ValueError as error:
        assert "character limit" in str(error)
    else:
        raise AssertionError("oversized text must be rejected")


def test_alignment_splits_verified_and_missing_with_sources() -> None:
    alignment = align_jd_to_evidence("octocat", JD_TEXT, _evidence())

    verified = {skill.skill for skill in alignment.skills if skill.status == "verified"}
    missing = [skill.skill for skill in alignment.skills if skill.status == "unverified"]

    assert "Python" in verified
    assert "FastAPI" in verified
    assert "Container delivery" in verified
    assert "Database engineering" in missing
    assert "CI/CD pipelines" in missing
    fastapi_match = next(skill for skill in alignment.skills if skill.skill == "FastAPI")
    assert fastapi_match.evidence_sources
    github_sources = all(
        source.url.startswith("https://github.com/") for source in fastapi_match.evidence_sources
    )
    assert github_sources
    assert alignment.verified_count == len(verified)
    assert alignment.missing_skills == missing
    assert alignment.requirements_considered == len(alignment.skills)


def test_missing_skills_ordered_by_demand_frequency() -> None:
    text = (
        "PostgreSQL PostgreSQL PostgreSQL. SQL SQL. Monitoring once. Some Django. Some more Django."
    )
    alignment = align_jd_to_evidence("octocat", text, _evidence())
    missing = [skill.skill for skill in alignment.skills if skill.status == "unverified"]
    assert missing[0] == "Database engineering"
    database = next(skill for skill in alignment.skills if skill.skill == "Database engineering")
    assert database.mentions >= 5


def test_unrecognized_description_produces_no_claims() -> None:
    alignment = align_jd_to_evidence(
        "octocat",
        "We are a friendly team seeking a culture fit with great communication skills.",
        _evidence(),
    )
    assert alignment.skills == []
    assert alignment.missing_skills == []
    assert "No recognizable technical requirements" in alignment.suggested_summary


KNOWN_EVIDENCE_KEYS = {
    "python.project",
    "api.framework.fastapi",
    "api.framework.django",
    "api.framework.flask",
    "testing.pytest",
    "database.tooling",
    "automation.github_actions",
    "delivery.container",
    "documentation.project",
    "frontend.app",
    "frontend.framework.react",
    "frontend.framework.vue",
    "frontend.framework.svelte",
    "frontend.framework.angular",
    "frontend.testing",
    "frontend.styling",
    "frontend.typescript",
    "react.app",
    "react.framework",
    "react.testing",
    "react.styling",
    "react.typescript",
    "infrastructure.as_code",
    "infrastructure.observability",
    "infrastructure.secrets",
    "infrastructure.servicing",
}


def test_every_catalog_rule_maps_to_real_evidence_keys() -> None:
    for rule in JD_SKILL_RULES:
        assert rule.evidence_keys, rule.name
        assert set(rule.evidence_keys) <= KNOWN_EVIDENCE_KEYS, rule.name


def test_capability_highlights_deduplicate_and_cap() -> None:
    keys = [
        "python.project",
        "api.framework.fastapi",
        "react.framework",
        "react.app",
        "unknown.key",
        "delivery.container",
        "testing.pytest",
        "database.tooling",
        "documentation.project",
        "frontend.typescript",
    ]
    highlights = capability_highlights_from_keys(keys, limit=6)
    assert len(highlights) <= 6
    assert len(highlights) == len(set(highlights))
    assert "React" in highlights
    assert highlights[0] == "Python projects"


def _seed_completed_analysis(database_path: Path, analysis_id: str) -> None:
    evidence = _evidence()

    async def seed() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            analysis = await session.get(AnalysisRun, analysis_id)
            assert analysis is not None
            report = generate_report(evidence, "completed")
            analysis.status = "completed"
            analysis.evidence_snapshot = evidence.model_dump(mode="json")
            analysis.report_snapshot = report.model_dump(mode="json")
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())


def test_api_and_web_flow(tmp_path: Path) -> None:
    database_path = tmp_path / "jd.db"
    client = create_test_client(database_path)
    try:
        created = client.post(
            "/v1/analyses",
            json={"github_username": "octocat", "target_role": "python_backend_developer"},
        )
        analysis_id = created.json()["id"]
    finally:
        client.__exit__(None, None, None)

    _seed_completed_analysis(database_path, analysis_id)

    client = create_test_client(database_path)
    try:
        api = client.post(
            f"/v1/analyses/{analysis_id}/jd-alignment",
            json={"jd_text": JD_TEXT},
        )
        page_form = client.get(f"/reports/{analysis_id}/jd")
        page_result = client.post(
            f"/reports/{analysis_id}/jd",
            data={"jd_text": JD_TEXT},
        )
        too_short = client.post(
            f"/reports/{analysis_id}/jd",
            data={"jd_text": "tiny"},
        )
        missing_analysis = client.get("/reports/missing-id/jd")
        report_page = client.get(f"/reports/{analysis_id}")
    finally:
        client.__exit__(None, None, None)

    assert api.status_code == 200
    body = api.json()
    assert body["verified_count"] >= 2
    assert "Database engineering" in body["missing_skills"]
    assert body["requirements_considered"] >= 5

    assert page_form.status_code == 200
    assert 'name="jd_text"' in page_form.text

    assert page_result.status_code == 200
    assert "vs this job description." in page_result.text
    assert "Preparation backlog" in page_result.text
    assert "demanded" in page_result.text

    assert too_short.status_code == 422
    assert 'role="alert"' in too_short.text
    assert "meaningful snippet" in too_short.text
    assert missing_analysis.status_code == 404

    assert report_page.status_code == 200
    assert "/reports/" + analysis_id + "/jd" in report_page.text
