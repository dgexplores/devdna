from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from devdna.database import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
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
    evidence_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    report_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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


class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"

    owner_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )


class RecruiterBatch(Base):
    __tablename__ = "recruiter_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(48), index=True)
    target_role: Mapped[str] = mapped_column(String(64))
    source_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class RecruiterCandidate(Base):
    __tablename__ = "recruiter_candidates"

    batch_id: Mapped[str] = mapped_column(
        ForeignKey("recruiter_batches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    github_username: Mapped[str] = mapped_column(String(39))
    position: Mapped[int]
