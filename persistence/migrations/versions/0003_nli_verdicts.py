"""Persist NLI pair distributions, final verdicts, and verdict evidence links."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_nli_verdicts"
down_revision: Union[str, None] = "0002_dense_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add run-scoped semantic outputs and document-scoped evidence provenance."""
    bind = op.get_bind()
    json_type = (
        postgresql.JSONB(none_as_null=True)
        if bind.dialect.name == "postgresql"
        else sa.JSON(none_as_null=True)
    )
    op.create_table(
        "nli_results",
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
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("contradiction_score", sa.Float(), nullable=False),
        sa.Column("entailment_score", sa.Float(), nullable=False),
        sa.Column("neutral_score", sa.Float(), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("model_revision", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "label IN ('entailment', 'contradiction', 'neutral')",
            name="ck_nli_results_label",
        ),
        sa.CheckConstraint(
            "contradiction_score >= 0 AND contradiction_score <= 1 AND "
            "entailment_score >= 0 AND entailment_score <= 1 AND "
            "neutral_score >= 0 AND neutral_score <= 1",
            name="ck_nli_results_score_range",
        ),
        sa.UniqueConstraint(
            "run_id", "claim_id", "evidence_chunk_id", name="uq_nli_result_pair"
        ),
    )
    op.create_index("ix_nli_results_run_id", "nli_results", ["run_id"])
    op.create_index("ix_nli_results_claim_id", "nli_results", ["claim_id"])
    op.create_index(
        "ix_nli_results_evidence_chunk_id", "nli_results", ["evidence_chunk_id"]
    )

    op.create_table(
        "verdicts",
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
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("explanation", json_type, nullable=False, server_default="[]"),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "status IN ('Supported', 'Partially Supported', 'Contradicted', "
            "'Unsupported', 'Needs Review')",
            name="ck_verdicts_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_verdicts_confidence_range",
        ),
        sa.UniqueConstraint("run_id", "claim_id", name="uq_verdict_run_claim"),
    )
    op.create_index("ix_verdicts_run_id", "verdicts", ["run_id"])
    op.create_index("ix_verdicts_claim_id", "verdicts", ["claim_id"])

    op.create_table(
        "verdict_evidence",
        sa.Column(
            "verdict_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("verdicts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_chunk_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("evidence_chunks.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    """Remove semantic results and verdict provenance."""
    op.drop_table("verdict_evidence")
    op.drop_index("ix_verdicts_claim_id", table_name="verdicts")
    op.drop_index("ix_verdicts_run_id", table_name="verdicts")
    op.drop_table("verdicts")
    op.drop_index("ix_nli_results_evidence_chunk_id", table_name="nli_results")
    op.drop_index("ix_nli_results_claim_id", table_name="nli_results")
    op.drop_index("ix_nli_results_run_id", table_name="nli_results")
    op.drop_table("nli_results")
