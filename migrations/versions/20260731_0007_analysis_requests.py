"""Track analysis ownership without duplicating public analysis work."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0007"
down_revision: str | Sequence[str] | None = "20260730_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_requests",
        sa.Column("owner_id", sa.String(length=48), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_runs.id"],
            name=op.f("fk_analysis_requests_analysis_id_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_id", "analysis_id", name=op.f("pk_analysis_requests")),
    )
    op.create_index(
        op.f("ix_analysis_requests_requested_at"),
        "analysis_requests",
        ["requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_analysis_requests_requested_at"), table_name="analysis_requests")
    op.drop_table("analysis_requests")
