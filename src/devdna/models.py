from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from devdna.database import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="valid_status",
        ),
        Index(
            "uq_active_analysis",
            "github_username",
            "target_role",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    github_username: Mapped[str] = mapped_column(String(39), index=True)
    target_role: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    profile_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
