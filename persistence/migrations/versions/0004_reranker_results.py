"""Persist run-scoped reranker scores with their evidence provenance."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_reranker_results"
down_revision: Union[str, None] = "0003_nli_verdicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create immutable claim-evidence relevance score rows."""
    op.create_table(
        "reranker_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_chunk_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("evidence_chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("model_revision", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_reranker_results_score_range",
        ),
        sa.UniqueConstraint(
            "run_id", "claim_id", "evidence_chunk_id", name="uq_reranker_result_pair"
        ),
    )
    op.create_index("ix_reranker_results_run_id", "reranker_results", ["run_id"])
    op.create_index("ix_reranker_results_claim_id", "reranker_results", ["claim_id"])
    op.create_index(
        "ix_reranker_results_evidence_chunk_id",
        "reranker_results",
        ["evidence_chunk_id"],
    )


def downgrade() -> None:
    """Remove run-scoped relevance score rows."""
    op.drop_index("ix_reranker_results_evidence_chunk_id", table_name="reranker_results")
    op.drop_index("ix_reranker_results_claim_id", table_name="reranker_results")
    op.drop_index("ix_reranker_results_run_id", table_name="reranker_results")
    op.drop_table("reranker_results")
