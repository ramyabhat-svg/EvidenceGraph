"""Record when an analysis run completed."""

import sqlalchemy as sa
from alembic import op

revision = "0008_run_completion_time"
down_revision = "0007_policy_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable timestamp so historical run rows remain valid."""
    op.add_column(
        "analysis_runs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the run completion timestamp."""
    op.drop_column("analysis_runs", "completed_at")
