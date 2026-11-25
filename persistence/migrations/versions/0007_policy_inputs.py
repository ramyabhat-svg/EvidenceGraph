"""Persist the exact ordered inputs used by new verdicts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_policy_inputs"
down_revision = "0006_review_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable snapshot field for compatibility with historical runs."""
    json_type = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
    op.add_column("verdicts", sa.Column("policy_inputs", json_type, nullable=True))


def downgrade() -> None:
    """Remove the policy input snapshots."""
    op.drop_column("verdicts", "policy_inputs")
