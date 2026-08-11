import logging
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from rq import Queue, Retry
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.cv import CvFileError, align_cv_to_evidence, extract_cv_text
from devdna.database import get_session
from devdna.jobs import collect_profile_job
from devdna.learning import generate_learning_plan
from devdna.models import AnalysisRequest, AnalysisRun
from devdna.readme import generate_profile_readme
from devdna.schemas import (
    AnalysisCreate,
    AnalysisResponse,
    CvAlignment,
    EvidenceSnapshot,
    LearningPlan,
    ReadmeDraft,
    ReportSnapshot,
)
from devdna.security import authenticate_api_client, authorize_analysis_creation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/analyses", tags=["analyses"])


def get_queue(request: Request) -> Queue:
    return cast(Queue, request.app.state.queue)


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
QueueDependency = Annotated[Queue, Depends(get_queue)]
OwnerDependency = Annotated[str, Depends(authenticate_api_client)]


async def find_active_analysis(
    session: AsyncSession,
    payload: AnalysisCreate,
) -> AnalysisRun | None:
    return cast(
        AnalysisRun | None,
        await session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.github_username == payload.github_username,
                AnalysisRun.target_role == payload.target_role,
                AnalysisRun.status.in_(("queued", "running")),
            )
        ),
    )


async def start_analysis(
    payload: AnalysisCreate,
    session: AsyncSession,
    queue: Queue,
    owner_id: str,
) -> AnalysisRun:
    """Persist and enqueue one idempotent analysis request."""
    existing = await find_active_analysis(session, payload)
    if existing:
        await record_analysis_request(session, owner_id, existing.id)
        try:
            queued_job = queue.fetch_job(existing.id)
        except Exception as error:
            logger.exception("Could not inspect queue job for analysis %s", existing.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Analysis queue unavailable",
            ) from error
        if queued_job is None:
            existing.status = "queued"
            existing.error_message = None
            await session.commit()
            await session.refresh(existing)
            enqueue_analysis(queue, existing)
        return existing

    analysis = AnalysisRun(
        id=str(uuid4()),
        github_username=payload.github_username,
        target_role=payload.target_role,
        status="queued",
    )
    session.add(analysis)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await find_active_analysis(session, payload)
        if existing:
            return existing
        raise
    await session.refresh(analysis)
    await record_analysis_request(session, owner_id, analysis.id)

    try:
        enqueue_analysis(queue, analysis)
    except HTTPException:
        analysis.status = "failed"
        analysis.error_message = "Analysis queue unavailable"
        await session.commit()
        raise
    return analysis


async def record_analysis_request(
    session: AsyncSession,
    owner_id: str,
    analysis_id: str,
) -> None:
    await session.merge(AnalysisRequest(owner_id=owner_id, analysis_id=analysis_id))
    await session.commit()


async def analyses_for_owner(
    session: AsyncSession,
    owner_id: str,
    limit: int,
) -> list[AnalysisRun]:
    result = await session.scalars(
        select(AnalysisRun)
        .join(AnalysisRequest, AnalysisRequest.analysis_id == AnalysisRun.id)
        .where(AnalysisRequest.owner_id == owner_id)
        .order_by(AnalysisRequest.requested_at.desc())
        .limit(limit)
    )
    return list(result)


async def owner_requested_analysis(
    session: AsyncSession,
    owner_id: str,
    analysis_id: str,
) -> bool:
    request_record = await session.get(AnalysisRequest, (owner_id, analysis_id))
    return request_record is not None


def enqueue_analysis(queue: Queue, analysis: AnalysisRun) -> None:
    try:
        queue.enqueue(
            collect_profile_job,
            analysis.id,
            job_id=analysis.id,
            job_timeout=300,
            result_ttl=0,
            failure_ttl=86400,
            retry=Retry(max=2, interval=[30, 120]),
        )
    except Exception as error:
        logger.exception("Could not enqueue analysis %s", analysis.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis queue unavailable",
        ) from error


@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(authorize_analysis_creation)],
)
async def create_analysis(
    payload: AnalysisCreate,
    request: Request,
    session: SessionDependency,
    queue: QueueDependency,
) -> AnalysisRun:
    owner_id = request.state.api_client_id or "public"
    return await start_analysis(payload, session, queue, owner_id)


@router.get("", response_model=list[AnalysisResponse])
async def list_analyses(
    session: SessionDependency,
    owner_id: OwnerDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AnalysisRun]:
    return await analyses_for_owner(session, owner_id, limit)


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    session: SessionDependency,
) -> AnalysisRun:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    return analysis


@router.get("/{analysis_id}/report", response_model=ReportSnapshot)
async def get_analysis_report(
    analysis_id: str,
    session: SessionDependency,
) -> ReportSnapshot:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report is not ready",
        )
    return ReportSnapshot.model_validate(analysis.report_snapshot)


@router.get("/{analysis_id}/readme", response_model=ReadmeDraft)
async def get_analysis_readme(
    analysis_id: str,
    session: SessionDependency,
    style: str = Query(default="minimal", pattern="^(minimal|badges|centered)$"),
) -> ReadmeDraft:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="README draft is not ready",
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    return generate_profile_readme(analysis.github_username, report, style=style)


@router.get("/{analysis_id}/learning", response_model=LearningPlan)
async def get_analysis_learning_plan(
    analysis_id: str,
    session: SessionDependency,
) -> LearningPlan:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    if analysis.report_snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Learning plan is not ready",
        )
    report = ReportSnapshot.model_validate(analysis.report_snapshot)
    return generate_learning_plan(report)


@router.post("/{analysis_id}/cv-alignment", response_model=CvAlignment)
async def create_cv_alignment(
    analysis_id: str,
    request: Request,
    session: SessionDependency,
    owner_id: OwnerDependency,
    file: Annotated[UploadFile, File()],
) -> CvAlignment:
    analysis = await session.get(AnalysisRun, analysis_id)
    if analysis is None or not await owner_requested_analysis(session, owner_id, analysis_id):
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
        text = extract_cv_text(
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
    evidence = EvidenceSnapshot.model_validate(analysis.evidence_snapshot)
    return align_cv_to_evidence(
        analysis.github_username,
        file.filename or "",
        text,
        evidence,
    )
