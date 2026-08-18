from pathlib import Path
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from devdna.analyses import get_queue, start_analysis
from devdna.database import get_session
from devdna.models import AnalysisRun, RecruiterBatch, RecruiterCandidate
from devdna.recruiter_files import RecruiterFileError, parse_recruiter_file
from devdna.rubrics import supported_roles
from devdna.schemas import (
    AnalysisCreate,
    AnalysisStatus,
    RecruiterBatchResponse,
    RecruiterCandidateResult,
    ReportSnapshot,
)
from devdna.security import authenticate_api_client, authorize_recruiter_batch

router = APIRouter(prefix="/v1/recruiter", tags=["recruiter"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
QueueDependency = Annotated[Queue, Depends(get_queue)]
OwnerDependency = Annotated[str, Depends(authenticate_api_client)]
BatchOwnerDependency = Annotated[str, Depends(authorize_recruiter_batch)]


def rank_candidates(candidates: list[RecruiterCandidateResult]) -> None:
    ranked = sorted(
        (candidate for candidate in candidates if candidate.requirements_met is not None),
        key=lambda candidate: (
            -(candidate.requirements_met or 0),
            candidate.github_username,
        ),
    )
    for rank, candidate in enumerate(ranked, start=1):
        candidate.rank = rank
    candidates.sort(key=lambda candidate: (candidate.rank is None, candidate.rank or 0))


async def batch_response(
    batch: RecruiterBatch,
    session: AsyncSession,
) -> RecruiterBatchResponse:
    rows = await session.execute(
        select(RecruiterCandidate, AnalysisRun)
        .join(AnalysisRun, AnalysisRun.id == RecruiterCandidate.analysis_id)
        .where(RecruiterCandidate.batch_id == batch.id)
        .order_by(RecruiterCandidate.position)
    )
    candidates: list[RecruiterCandidateResult] = []
    for candidate, analysis in rows:
        report = (
            ReportSnapshot.model_validate(analysis.report_snapshot)
            if analysis.report_snapshot
            else None
        )
        candidates.append(
            RecruiterCandidateResult(
                rank=None,
                analysis_id=analysis.id,
                github_username=candidate.github_username,
                status=cast(AnalysisStatus, analysis.status),
                requirements_met=report.requirements_met if report else None,
                requirements_total=report.requirements_total if report else None,
                alignment_label=report.alignment_label if report else None,
                strengths=[item.title for item in report.strengths] if report else [],
                gaps=[item.title for item in report.gaps] if report else [],
            )
        )

    rank_candidates(candidates)
    return RecruiterBatchResponse(
        id=batch.id,
        target_role=batch.target_role,
        source_filename=batch.source_filename,
        created_at=batch.created_at,
        candidates=candidates,
    )


@router.post(
    "/batches",
    response_model=RecruiterBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_recruiter_batch(
    request: Request,
    session: SessionDependency,
    queue: QueueDependency,
    owner_id: BatchOwnerDependency,
    file: Annotated[UploadFile, File()],
    target_role: Annotated[str, Form()] = "python_backend_developer",
) -> RecruiterBatchResponse:
    settings = request.app.state.settings
    content = await file.read(settings.recruiter_upload_max_bytes + 1)
    if len(content) > settings.recruiter_upload_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Recruiter upload is too large",
        )
    return await create_batch(
        owner_id,
        file.filename or "",
        content,
        target_role,
        session,
        queue,
        settings.recruiter_batch_max_candidates,
    )


async def create_batch(
    owner_id: str,
    source_filename: str,
    content: bytes,
    target_role: str,
    session: AsyncSession,
    queue: Queue,
    maximum_candidates: int,
) -> RecruiterBatchResponse:
    if target_role not in supported_roles():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported target role",
        )
    filename = Path(source_filename).name[:255]
    try:
        usernames = parse_recruiter_file(
            filename,
            content,
            maximum_candidates,
        )
    except RecruiterFileError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    batch = RecruiterBatch(
        id=str(uuid4()),
        owner_id=owner_id,
        target_role=target_role,
        source_filename=filename,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    for position, username in enumerate(usernames):
        payload = AnalysisCreate.model_validate(
            {"github_username": username, "target_role": target_role}
        )
        analysis = await start_analysis(payload, session, queue, owner_id)
        session.add(
            RecruiterCandidate(
                batch_id=batch.id,
                analysis_id=analysis.id,
                github_username=username,
                position=position,
            )
        )
        await session.commit()
    return await batch_response(batch, session)


@router.get("/batches/{batch_id}", response_model=RecruiterBatchResponse)
async def get_recruiter_batch(
    batch_id: str,
    session: SessionDependency,
    owner_id: OwnerDependency,
) -> RecruiterBatchResponse:
    batch = await session.get(RecruiterBatch, batch_id)
    if batch is None or batch.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return await batch_response(batch, session)
