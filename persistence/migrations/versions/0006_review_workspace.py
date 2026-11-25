"""Add optional presentation metadata and human review events."""

import sqlalchemy as sa
from alembic import op

revision = "0006_review_workspace"
down_revision = "0005_one_companion_csv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve existing projects and documents when enabling review."""
    op.add_column("projects", sa.Column("name", sa.String(255)))
    op.add_column("projects", sa.Column("description", sa.Text()))
    op.add_column("projects", sa.Column("created_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("display_name", sa.String(512)))
    op.add_column("documents", sa.Column("uploaded_at", sa.DateTime(timezone=True)))
    op.create_table(
        "workspace_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("verdict_id", sa.Uuid(), sa.ForeignKey("verdicts.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(255), nullable=False),
        sa.Column("override_verdict", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("flag_for_rerun", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_workspace_reviews_verdict_id", "workspace_reviews", ["verdict_id"])


def downgrade() -> None:
    """Remove workspace metadata and reviews."""
    op.drop_table("workspace_reviews")
    for table, fields in (
        ("documents", ("uploaded_at", "display_name")),
        ("projects", ("created_at", "description", "name")),
    ):
        for field in fields:
            op.drop_column(table, field)
