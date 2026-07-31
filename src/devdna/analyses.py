import logging
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from rq import Queue, Retry
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.database import get_session
from devdna.jobs import collect_profile_job
from devdna.learning import generate_learning_plan
from devdna.models import AnalysisRun
from devdna.readme import generate_profile_readme
from devdna.schemas import (
    AnalysisCreate,
    AnalysisResponse,
    LearningPlan,
    ReadmeDraft,
    ReportSnapshot,
)
from devdna.security import authorize_analysis_creation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/analyses", tags=["analyses"])


def get_queue(request: Request) -> Queue:
    return cast(Queue, request.app.state.queue)


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
QueueDependency = Annotated[Queue, Depends(get_queue)]


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
) -> AnalysisRun:
    """Persist and enqueue one idempotent analysis request."""
    existing = await find_active_analysis(session, payload)
    if existing:
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

    try:
        enqueue_analysis(queue, analysis)
    except HTTPException:
        analysis.status = "failed"
        analysis.error_message = "Analysis queue unavailable"
        await session.commit()
        raise
    return analysis


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
    session: SessionDependency,
    queue: QueueDependency,
) -> AnalysisRun:
    return await start_analysis(payload, session, queue)


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
    return generate_profile_readme(analysis.github_username, report)


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
