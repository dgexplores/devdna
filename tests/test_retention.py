import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from devdna.database import Base
from devdna.models import AnalysisRun, RecruiterBatch
from devdna.retention import purge_expired_analyses, purge_expired_recruiter_batches


def analysis(analysis_id: str, status: str, updated_at: datetime) -> AnalysisRun:
    return AnalysisRun(
        id=analysis_id,
        github_username=analysis_id,
        target_role="python_backend_developer",
        status=status,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_retention_deletes_only_expired_terminal_analyses_in_bounded_batches(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        now = datetime(2026, 7, 30, tzinfo=UTC)
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retention.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessions() as session:
            session.add_all(
                [
                    analysis("expired-complete", "completed", now - timedelta(days=91)),
                    analysis("expired-failed", "failed", now - timedelta(days=92)),
                    analysis("active-running", "running", now - timedelta(days=100)),
                    analysis("recent-complete", "completed", now - timedelta(days=10)),
                ]
            )
            await session.commit()

            first_deleted = await purge_expired_analyses(
                session,
                retention_days=90,
                batch_size=1,
                now=now,
            )
            second_deleted = await purge_expired_analyses(
                session,
                retention_days=90,
                batch_size=10,
                now=now,
            )

            assert first_deleted == 1
            assert second_deleted == 1
            assert await session.get(AnalysisRun, "active-running") is not None
            assert await session.get(AnalysisRun, "recent-complete") is not None
        await engine.dispose()

    asyncio.run(scenario())


def test_retention_deletes_expired_recruiter_batches(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 7, 30, tzinfo=UTC)
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch-retention.db'}")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with sessions() as session:
            session.add_all(
                [
                    RecruiterBatch(
                        id="expired",
                        owner_id="recruiter",
                        target_role="python_backend_developer",
                        source_filename="old.csv",
                        created_at=now - timedelta(days=91),
                    ),
                    RecruiterBatch(
                        id="recent",
                        owner_id="recruiter",
                        target_role="python_backend_developer",
                        source_filename="new.csv",
                        created_at=now - timedelta(days=2),
                    ),
                ]
            )
            await session.commit()

            deleted = await purge_expired_recruiter_batches(session, 90, 10, now=now)

            assert deleted == 1
            assert await session.get(RecruiterBatch, "recent") is not None
        await engine.dispose()

    asyncio.run(scenario())
