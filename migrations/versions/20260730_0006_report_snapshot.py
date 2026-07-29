"""Store explainable report snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0006"
down_revision: str | Sequence[str] | None = "20260730_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("report_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "report_snapshot")
