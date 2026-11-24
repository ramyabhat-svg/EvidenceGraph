"""Create the initial EvidenceGraph persistence foundation."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_persistence_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type() -> sa.types.TypeEngine[object]:
    """Return JSON with PostgreSQL JSONB storage."""
    return sa.JSON(none_as_null=True).with_variant(
        postgresql.JSONB(none_as_null=True), "postgresql"
    )


def upgrade() -> None:
    """Create project, document, source, claim, run, and verification tables."""
    uuid_type = sa.Uuid(as_uuid=True)
    json_type = _json_type()

    op.create_table(
        "projects",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            uuid_type,
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_document_id", uuid_type, sa.ForeignKey("documents.id", ondelete="RESTRICT")
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("processing_error", sa.String(64)),
        sa.CheckConstraint("file_type IN ('pdf', 'csv')", name="ck_documents_file_type"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'error')",
            name="ck_documents_status",
        ),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index(
        "uq_documents_project_pdf_hash",
        "documents",
        ["project_id", "file_hash"],
        unique=True,
        postgresql_where=sa.text("file_type = 'pdf'"),
        sqlite_where=sa.text("file_type = 'pdf'"),
    )
    op.create_table(
        "source_locations",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            uuid_type,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("anchor_id", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("table_index", sa.Integer()),
        sa.Column("row", sa.Integer()),
        sa.Column("col", sa.Integer()),
        sa.Column("char_start", sa.Integer()),
        sa.Column("char_end", sa.Integer()),
        sa.Column("bbox", json_type),
        sa.Column("low_quality", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("low_quality_reasons", json_type, nullable=False),
        sa.Column("extraction_method", sa.String(128), nullable=False),
        sa.Column("parser_version", sa.String(128), nullable=False),
        sa.UniqueConstraint("document_id", "anchor_id", name="uq_source_location_document_anchor"),
        sa.UniqueConstraint("id", "document_id", name="uq_source_location_id_document_id"),
        sa.CheckConstraint(
            "kind IN ('paragraph', 'table_row', 'table_cell', 'csv_row')",
            name="ck_source_locations_kind",
        ),
    )
    op.create_index("ix_source_locations_document_id", "source_locations", ["document_id"])
    op.create_table(
        "evidence_chunks",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_chunk_id", uuid_type, nullable=False),
        sa.Column(
            "document_id",
            uuid_type,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_location_id",
            uuid_type,
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("headers", json_type, nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("cells", json_type),
        sa.UniqueConstraint(
            "document_id", "source_chunk_id", name="uq_evidence_document_source_chunk"
        ),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_evidence_document_ordinal"),
        sa.ForeignKeyConstraint(
            ["source_location_id", "document_id"],
            ["source_locations.id", "source_locations.document_id"],
            name="fk_evidence_chunk_source_location_document",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_evidence_chunks_document_id", "evidence_chunks", ["document_id"])
    op.create_table(
        "claims",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("extractor_claim_id", uuid_type, nullable=False),
        sa.Column(
            "document_id",
            uuid_type,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_location_id",
            uuid_type,
            nullable=False,
        ),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False),
        sa.Column("source_anchor_id", sa.String(256), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("numeric_slots", json_type, nullable=False),
        sa.Column("extraction_method", sa.String(128), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("low_quality", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint(
            "document_id", "extractor_claim_id", name="uq_claims_document_extractor_id"
        ),
        sa.ForeignKeyConstraint(
            ["source_location_id", "document_id"],
            ["source_locations.id", "source_locations.document_id"],
            name="fk_claims_source_location_document",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "claim_type IN ('quantitative', 'comparative', 'temporal', 'citation', "
            "'categorical', 'other')",
            name="ck_claims_type",
        ),
    )
    op.create_index("ix_claims_document_id", "claims", ["document_id"])
    op.create_table(
        "analysis_runs",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            uuid_type,
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("configuration", json_type, nullable=False),
        sa.Column("model_versions", json_type, nullable=False),
        sa.Column("policy_version", sa.String(128)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_analysis_runs_document_id", "analysis_runs", ["document_id"])
    op.create_table(
        "verification_results",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            uuid_type,
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id", uuid_type, sa.ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("result_type", sa.String(32), nullable=False),
        sa.Column("result_key", sa.String(128), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(256)),
        sa.Column("validator", sa.String(128)),
        sa.Column("slot_index", sa.Integer()),
        sa.Column("assumptions", json_type, nullable=False),
        sa.Column("trace", json_type, nullable=False),
        sa.UniqueConstraint(
            "run_id", "claim_id", "result_type", "result_key", name="uq_verification_result_key"
        ),
        sa.CheckConstraint(
            "result_type IN ('numeric_slot', 'domain_validator')",
            name="ck_verification_results_type",
        ),
        sa.CheckConstraint(
            "result IN ('match', 'mismatch', 'incomparable', 'not_applicable')",
            name="ck_verification_results_result",
        ),
    )
    op.create_index("ix_verification_results_run_id", "verification_results", ["run_id"])
    op.create_index("ix_verification_results_claim_id", "verification_results", ["claim_id"])
    op.create_table(
        "verification_evidence",
        sa.Column(
            "verification_result_id",
            uuid_type,
            sa.ForeignKey("verification_results.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_chunk_id",
            uuid_type,
            sa.ForeignKey("evidence_chunks.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_table(
        "numeric_checks",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "verification_result_id",
            uuid_type,
            sa.ForeignKey("verification_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_chunk_id",
            uuid_type,
            sa.ForeignKey("evidence_chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("check_index", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("claim_slots", json_type, nullable=False),
        sa.Column("evidence_slots", json_type, nullable=False),
        sa.Column("tolerance", sa.Numeric()),
        sa.Column("difference", sa.Numeric()),
        sa.Column("failed_slots", json_type, nullable=False),
        sa.Column("trace", json_type, nullable=False),
        sa.Column("validator_version", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "verification_result_id", "check_index", name="uq_numeric_check_result_index"
        ),
        sa.CheckConstraint(
            "result IN ('match', 'mismatch', 'incomparable', 'not_applicable')",
            name="ck_numeric_checks_result",
        ),
    )
    op.create_index(
        "ix_numeric_checks_verification_result_id", "numeric_checks", ["verification_result_id"]
    )
    op.create_index("ix_numeric_checks_evidence_chunk_id", "numeric_checks", ["evidence_chunk_id"])


def downgrade() -> None:
    """Drop the persistence foundation in reverse dependency order."""
    op.drop_index("ix_numeric_checks_evidence_chunk_id", table_name="numeric_checks")
    op.drop_index("ix_numeric_checks_verification_result_id", table_name="numeric_checks")
    op.drop_table("numeric_checks")
    op.drop_table("verification_evidence")
    op.drop_index("ix_verification_results_claim_id", table_name="verification_results")
    op.drop_index("ix_verification_results_run_id", table_name="verification_results")
    op.drop_table("verification_results")
    op.drop_index("ix_analysis_runs_document_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_index("ix_claims_document_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_evidence_chunks_document_id", table_name="evidence_chunks")
    op.drop_table("evidence_chunks")
    op.drop_index("ix_source_locations_document_id", table_name="source_locations")
    op.drop_table("source_locations")
    op.drop_index("uq_documents_project_pdf_hash", table_name="documents")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("projects")
