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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEVDNA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
