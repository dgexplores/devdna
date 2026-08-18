from typing import Literal

from devdna.rubrics import get_rubric
from devdna.schemas import (
    EvidenceItem,
    EvidenceSnapshot,
    EvidenceSource,
    ReportAction,
    ReportGap,
    ReportSnapshot,
    ReportStrength,
)

REPORT_SCHEMA_VERSION = "1"
REPORT_VERSION = "python-backend-report-v1"
REPORT_VERSIONS = {
    "python_backend_developer": "python-backend-report-v1",
    "frontend_react_developer": "frontend-react-report-v1",
    "frontend_developer": "frontend-report-v1",
    "devops_engineer": "devops-report-v1",
}


def report_version_for(role: str) -> str:
    return REPORT_VERSIONS.get(role, "devdna-report-v1")


def unique_sources(items: list[EvidenceItem]) -> list[EvidenceSource]:
    sources: dict[tuple[str, str], EvidenceSource] = {}
    for item in items:
        for source in item.sources:
            sources[(source.repository, source.path)] = source
    return [sources[key] for key in sorted(sources)]


def alignment_label(requirements_met: int, requirements_total: int) -> str:
    if requirements_met == requirements_total:
        return "Well-evidenced role alignment"
    if requirements_met >= max(1, requirements_total // 2):
        return "Developing role alignment"
    return "Foundational role alignment"


def generate_report(
    evidence: EvidenceSnapshot,
    collection_status: Literal["completed", "partial"],
    warning: str | None = None,
) -> ReportSnapshot:
    if collection_status not in {"completed", "partial"}:
        raise ValueError(f"unsupported collection status: {collection_status}")
    rubric = get_rubric(evidence.target_role)
    if evidence.rubric_version != rubric.version:
        raise ValueError("evidence rubric version does not match the active rubric")

    strengths: list[ReportStrength] = []
    gaps: list[ReportGap] = []
    actions: list[ReportAction] = []
    for requirement in rubric.requirements:
        matches = [item for item in evidence.items if item.key in requirement.evidence_keys]
        if matches:
            repositories = sorted({item.repository for item in matches})
            repository_word = "repository" if len(repositories) == 1 else "repositories"
            strengths.append(
                ReportStrength(
                    requirement=requirement.key,
                    title=requirement.title,
                    summary=(
                        f"{requirement.description} Verified in {len(repositories)} "
                        f"{repository_word}."
                    ),
                    repositories=repositories,
                    sources=unique_sources(matches),
                )
            )
            continue

        explanation = (
            f"{requirement.description} This was not verified in the available inspection data."
            if collection_status == "partial"
            else f"{requirement.description} No matching repository evidence was found."
        )
        gaps.append(
            ReportGap(
                requirement=requirement.key,
                title=requirement.title,
                explanation=explanation,
            )
        )
        actions.append(
            ReportAction(
                priority=len(actions) + 1,
                requirement=requirement.key,
                title=requirement.action_title,
                rationale=requirement.action_detail,
                evidence_needed=list(requirement.evidence_needed),
                solution=requirement.solution or None,
                template=requirement.template,
            )
        )

    return ReportSnapshot(
        schema_version=REPORT_SCHEMA_VERSION,
        report_version=report_version_for(evidence.target_role),
        analyzer_version=evidence.analyzer_version,
        rubric_version=evidence.rubric_version,
        target_role=evidence.target_role,
        collection_status=collection_status,
        warning=warning,
        alignment_label=alignment_label(len(strengths), len(rubric.requirements)),
        requirements_met=len(strengths),
        requirements_total=len(rubric.requirements),
        tech_stack=evidence.technologies,
        strengths=strengths,
        gaps=gaps,
        actions=actions,
    )
