"""Allow partial analysis results."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0004"
down_revision: str | Sequence[str] | None = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_analysis_runs_valid_status"),
        "analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_analysis_runs_valid_status"),
        "analysis_runs",
        "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
    )


def downgrade() -> None:
    op.execute("UPDATE analysis_runs SET status = 'failed' WHERE status = 'partial'")
    op.drop_constraint(
        op.f("ck_analysis_runs_valid_status"),
        "analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_analysis_runs_valid_status"),
        "analysis_runs",
        "status IN ('queued', 'running', 'completed', 'failed')",
    )
