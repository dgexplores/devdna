import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from devdna.config import Settings, get_settings
from devdna.github import (
    GitHubClient,
    GitHubRateLimited,
    GitHubTransientError,
    GitHubUserNotFound,
    ResponseCache,
)
from devdna.models import AnalysisRun
from devdna.schemas import GitHubSnapshot

logger = logging.getLogger(__name__)
SnapshotFetcher = Callable[[str], Awaitable[GitHubSnapshot]]


async def collect_profile(
    analysis_id: str,
    sessions: async_sessionmaker[AsyncSession],
    fetch_snapshot: SnapshotFetcher,
) -> None:
    async with sessions() as session:
        analysis = await session.get(AnalysisRun, analysis_id)
        if analysis is None:
            logger.warning("Analysis %s no longer exists", analysis_id)
            return

        analysis.status = "running"
        analysis.error_message = None
        await session.commit()

        try:
            snapshot = await fetch_snapshot(analysis.github_username)
        except GitHubUserNotFound:
            analysis.status = "failed"
            analysis.error_message = "GitHub user not found"
        except GitHubRateLimited as error:
            analysis.status = "failed"
            analysis.error_message = (
                f"GitHub rate limit exceeded; retry after {error.reset_at}"
                if error.reset_at
                else "GitHub rate limit exceeded"
            )
        except GitHubTransientError:
            analysis.status = "failed"
            analysis.error_message = "Temporary GitHub failure; automatic retry scheduled"
            await session.commit()
            raise
        except Exception:
            analysis.status = "failed"
            analysis.error_message = "GitHub request failed"
            logger.exception("Profile collection failed for analysis %s", analysis_id)
        else:
            analysis.status = "completed"
            analysis.profile_snapshot = snapshot.model_dump(mode="json")
        await session.commit()


async def run_profile_collection(analysis_id: str, settings: Settings) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    redis = Redis.from_url(settings.redis_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    client = GitHubClient(settings, cache=cast(ResponseCache, redis))
    try:
        await collect_profile(analysis_id, sessions, client.get_snapshot)
    finally:
        await redis.aclose()
        await engine.dispose()


def collect_profile_job(analysis_id: str) -> None:
    asyncio.run(run_profile_collection(analysis_id, get_settings()))
