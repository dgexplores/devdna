"""Add owner-scoped recruiter batches and candidates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0008"
down_revision: str | Sequence[str] | None = "20260731_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiter_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=48), nullable=False),
        sa.Column("target_role", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recruiter_batches")),
    )
    op.create_index(
        op.f("ix_recruiter_batches_owner_id"),
        "recruiter_batches",
        ["owner_id"],
        unique=False,
    )
    op.create_table(
        "recruiter_candidates",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("github_username", sa.String(length=39), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_runs.id"],
            name=op.f("fk_recruiter_candidates_analysis_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["recruiter_batches.id"],
            name=op.f("fk_recruiter_candidates_batch_id_recruiter_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "batch_id",
            "analysis_id",
            name=op.f("pk_recruiter_candidates"),
        ),
    )


def downgrade() -> None:
    op.drop_table("recruiter_candidates")
    op.drop_index(op.f("ix_recruiter_batches_owner_id"), table_name="recruiter_batches")
    op.drop_table("recruiter_batches")
