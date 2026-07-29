from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://devdna:devdna@localhost:5432/devdna"
    redis_url: str = "redis://localhost:6379/0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_token: SecretStr | None = None
    github_timeout_seconds: float = Field(default=10, gt=0, le=60)
    api_keys: SecretStr | None = None
    analysis_rate_limit: int = Field(default=10, ge=1, le=1000)
    analysis_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    max_request_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)
    analysis_retention_days: int = Field(default=90, ge=1, le=3650)
    retention_batch_size: int = Field(default=500, ge=1, le=10_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEVDNA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
