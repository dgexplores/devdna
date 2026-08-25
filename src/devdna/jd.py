import re
from dataclasses import dataclass

from devdna.schemas import EvidenceSnapshot, EvidenceSource, JdAlignment, JdSkillMatch

JD_SCHEMA_VERSION = "1"
JD_ANALYZER_VERSION = "jd-github-alignment-v1"


class JdTextError(ValueError):
    pass


@dataclass(frozen=True)
class JdSkillRule:
    """Maps a job-description skill demand to evidence keys that can verify it."""

    name: str
    patterns: tuple[str, ...]
    evidence_keys: tuple[str, ...]


JD_SKILL_RULES = (
    JdSkillRule("Python", (r"\bpython(?:\s*3)?\b",), ("python.project",)),
    JdSkillRule("FastAPI", (r"\bfastapi\b",), ("api.framework.fastapi",)),
    JdSkillRule("Django", (r"\bdjango\b",), ("api.framework.django",)),
    JdSkillRule("Flask", (r"\bflask\b",), ("api.framework.flask",)),
    JdSkillRule(
        "REST API development",
        (
            r"\brest(?:ful)?\b",
            r"\bapi(?:s)?\s+(?:development|design|integration)\b",
            r"\bbackend\b",
        ),
        ("api.framework.fastapi", "api.framework.django", "api.framework.flask"),
    ),
    JdSkillRule(
        "Automated testing",
        (
            r"\bunit\s+tests?\b",
            r"\bintegration\s+tests?\b",
            r"\bautomated?\s+tests?\b",
            r"\btest\s+coverage\b",
            r"\btdd\b",
        ),
        ("testing.pytest", "react.testing", "frontend.testing"),
    ),
    JdSkillRule(
        "Database engineering",
        (r"\bpostgres(?:ql)?\b", r"\bsqlalchemy\b", r"\balembic\b", r"\bsql\b", r"\borm\b"),
        ("database.tooling",),
    ),
    JdSkillRule(
        "CI/CD pipelines",
        (
            r"\bci/?cd\b",
            r"\bc(?:ontinuous)\s+i(?:ntegration)\b",
            r"\bgithub actions\b",
            r"\bpipelines?\b",
        ),
        ("automation.github_actions",),
    ),
    JdSkillRule(
        "Container delivery",
        (r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b", r"\bcontainers?\b"),
        ("delivery.container",),
    ),
    JdSkillRule(
        "React",
        (r"\breact(?:\.?js)?\b", r"\bnext\.?js\b"),
        ("react.framework", "react.app", "frontend.framework.react"),
    ),
    JdSkillRule(
        "TypeScript",
        (r"\btypescript\b",),
        ("react.typescript", "frontend.typescript"),
    ),
    JdSkillRule(
        "Frontend engineering",
        (
            r"\bfront[- ]?end\b",
            r"\bspa\b",
            r"\bresponsive\s+(?:design|web)\b",
            r"\bui\s+(?:development|engineering)\b",
        ),
        ("frontend.app", "react.app"),
    ),
    JdSkillRule(
        "CSS and styling systems",
        (r"\bcss\b", r"\bscss\b", r"\bsass\b", r"\btailwind\b", r"\bstyling\b"),
        ("react.styling", "frontend.styling"),
    ),
    JdSkillRule(
        "Infrastructure as code",
        (r"\bterraform\b", r"\biac\b", r"\binfrastructure\s+as\s+code\b", r"\bcloudformation\b"),
        ("infrastructure.as_code",),
    ),
    JdSkillRule(
        "Observability",
        (r"\bmonitoring\b", r"\bobservability\b", r"\bgrafana\b", r"\bprometheus\b"),
        ("infrastructure.observability",),
    ),
    JdSkillRule(
        "Project documentation",
        (
            r"\bdocumentation\b",
            r"\btechnical\s+writing\b",
            r"\brfcs?\b",
            r"\badrs?\b",
        ),
        ("documentation.project",),
    ),
)


def validate_jd_text(text: str, *, max_characters: int) -> str:
    cleaned = text.strip()
    if len(cleaned) < 40:
        raise JdTextError("Paste at least a meaningful snippet of the job description")
    if len(cleaned) > max_characters:
        raise JdTextError(f"Job description text exceeds the {max_characters}-character limit")
    return cleaned


def count_mentions(patterns: tuple[str, ...], jd_text: str) -> int:
    return sum(len(re.findall(pattern, jd_text, re.IGNORECASE)) for pattern in patterns)


def align_jd_to_evidence(
    github_username: str,
    jd_text: str,
    evidence: EvidenceSnapshot,
) -> JdAlignment:
    """Deterministically match JD skill demands against saved repository evidence.

    Only saved evidence items can verify a skill; nothing else does.
    """
    indexed_evidence: dict[str, list[EvidenceSource]] = {}
    for item in evidence.items:
        indexed_evidence.setdefault(item.key, []).extend(item.sources)

    skills: list[JdSkillMatch] = []
    for rule in JD_SKILL_RULES:
        mentions = count_mentions(rule.patterns, jd_text)
        if mentions == 0:
            continue
        sources = [source for key in rule.evidence_keys for source in indexed_evidence.get(key, [])]
        skills.append(
            JdSkillMatch(
                skill=rule.name,
                mentions=mentions,
                status="verified" if sources else "unverified",
                evidence_sources=sources,
            )
        )

    skills.sort(
        key=lambda skill: (
            0 if skill.status == "unverified" else 1,
            -skill.mentions,
            skill.skill,
        )
    )

    verified = [skill for skill in skills if skill.status == "verified"]
    missing = [skill for skill in skills if skill.status == "unverified"]

    if not skills:
        summary = (
            "No recognizable technical requirements were found in this job description. "
            "Paste a section that lists the required skills."
        )
    elif verified and missing:
        summary = (
            f"Public GitHub work verifies {len(verified)} of {len(skills)} demanded skills. "
            f"Strongest gaps to close first: {', '.join(skill.skill for skill in missing[:3])}."
        )
    elif verified:
        summary = (
            f"Public GitHub work verifies all {len(verified)} recognized demands from this "
            "job description."
        )
    else:
        summary = (
            "None of the recognized job-description demands are verified by current public "
            f"GitHub evidence yet. Close {', '.join(skill.skill for skill in missing[:3])} first."
        )

    guidance = [
        "Verified rows link the exact public files that satisfy each demand; reference them "
        "directly in applications.",
        "Missing rows are ordered by how often the description demands them — treat them as "
        "your preparation backlog.",
        "Publish one reviewable project per missing skill, then rerun this analysis so the "
        "demand moves to verified.",
    ]

    return JdAlignment(
        schema_version=JD_SCHEMA_VERSION,
        analyzer_version=JD_ANALYZER_VERSION,
        github_username=github_username,
        requirements_considered=len(skills),
        skills=skills,
        verified_count=len(verified),
        missing_skills=[skill.skill for skill in missing],
        suggested_summary=summary,
        guidance=guidance,
    )


CAPABILITY_LABELS = {
    "python.project": "Python projects",
    "api.framework.fastapi": "FastAPI services",
    "api.framework.django": "Django apps",
    "api.framework.flask": "Flask apps",
    "testing.pytest": "Pytest suites",
    "database.tooling": "Database tooling",
    "automation.github_actions": "GitHub Actions CI",
    "delivery.container": "Container delivery",
    "documentation.project": "Project docs",
    "frontend.app": "Frontend apps",
    "frontend.framework.react": "React",
    "frontend.framework.vue": "Vue",
    "frontend.framework.svelte": "Svelte",
    "frontend.framework.angular": "Angular",
    "frontend.testing": "Frontend test runners",
    "frontend.styling": "Styling systems",
    "frontend.typescript": "TypeScript",
    "react.app": "React components",
    "react.framework": "React",
    "react.testing": "React tests",
    "react.styling": "Component styling",
    "react.typescript": "TypeScript React",
    "infrastructure.as_code": "Infrastructure as code",
    "infrastructure.observability": "Observability configs",
    "infrastructure.secrets": "Secret handling",
    "infrastructure.servicing": "Deployment configs",
}


def capability_highlights_from_keys(evidence_keys: list[str], *, limit: int = 6) -> list[str]:
    """Turn distinct evidence keys into concrete, recruiter-readable capabilities."""
    seen: dict[str, None] = {}
    for key in evidence_keys:
        label = CAPABILITY_LABELS.get(key)
        if label:
            seen.setdefault(label, None)
    return list(seen)[:limit]
