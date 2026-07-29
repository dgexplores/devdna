import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from devdna.config import Settings, get_settings
from devdna.models import AnalysisRun

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


async def run_retention(settings: Settings) -> int:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            return await purge_expired_analyses(
                session,
                settings.analysis_retention_days,
                settings.retention_batch_size,
            )
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    deleted = asyncio.run(run_retention(settings))
    print(json.dumps({"deleted_analyses": deleted}))


if __name__ == "__main__":
    main()
