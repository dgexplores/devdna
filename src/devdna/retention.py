import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from devdna.config import Settings, get_settings
from devdna.models import AnalysisRun, RecruiterBatch

TERMINAL_STATUSES = ("completed", "partial", "failed")


async def purge_expired_analyses(
    session: AsyncSession,
    retention_days: int,
    batch_size: int,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    result = await session.scalars(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.status.in_(TERMINAL_STATUSES),
            AnalysisRun.updated_at < cutoff,
        )
        .order_by(AnalysisRun.updated_at)
        .limit(batch_size)
    )
    analysis_ids = list(result)
    if not analysis_ids:
        return 0
    await session.execute(delete(AnalysisRun).where(AnalysisRun.id.in_(analysis_ids)))
    await session.commit()
    return len(analysis_ids)


async def purge_expired_recruiter_batches(
    session: AsyncSession,
    retention_days: int,
    batch_size: int,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    result = await session.scalars(
        select(RecruiterBatch.id)
        .where(RecruiterBatch.created_at < cutoff)
        .order_by(RecruiterBatch.created_at)
        .limit(batch_size)
    )
    batch_ids = list(result)
    if not batch_ids:
        return 0
    await session.execute(delete(RecruiterBatch).where(RecruiterBatch.id.in_(batch_ids)))
    await session.commit()
    return len(batch_ids)


async def run_retention(settings: Settings) -> dict[str, int]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            deleted_batches = await purge_expired_recruiter_batches(
                session,
                settings.analysis_retention_days,
                settings.retention_batch_size,
            )
            deleted_analyses = await purge_expired_analyses(
                session,
                settings.analysis_retention_days,
                settings.retention_batch_size,
            )
            return {
                "deleted_analyses": deleted_analyses,
                "deleted_recruiter_batches": deleted_batches,
            }
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    deleted = asyncio.run(run_retention(settings))
    print(json.dumps(deleted))


if __name__ == "__main__":
    main()
