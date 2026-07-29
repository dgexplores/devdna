"""Prevent duplicate active analyses."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0003"
down_revision: str | Sequence[str] | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_active_analysis",
        "analysis_runs",
        ["github_username", "target_role"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_analysis", table_name="analysis_runs")
