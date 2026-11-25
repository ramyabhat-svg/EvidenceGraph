"""SQLAlchemy persistence models for the approved domain contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Base class for persistence models."""


class ExactDecimal(TypeDecorator[Decimal]):
    """Store unbounded NUMERIC values and preserve exact decimals in SQLite tests."""

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "sqlite":
            from sqlalchemy import String as SqlString

            return dialect.type_descriptor(SqlString())
        return dialect.type_descriptor(Numeric())

    def process_bind_param(self, value: Decimal | None, dialect: Any) -> Any:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
        if dialect.name == "sqlite":
            return format(decimal_value, "f")
        return decimal_value

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


JSON_VALUE = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class ProjectRow(Base):
    """Project container for documents and project-scoped duplicate detection."""

    __tablename__ = "projects"

    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class DocumentRow(Base):
    """Persist one uploaded file, including an optional parent PDF relationship."""

    __tablename__ = "documents"

    display_name: Mapped[str | None] = mapped_column(String(512))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("file_type IN ('pdf', 'csv')", name="ck_documents_file_type"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'error')",
            name="ck_documents_status",
        ),
        Index(
            "uq_documents_project_pdf_hash",
            "project_id",
            "file_hash",
            unique=True,
            postgresql_where=text("file_type = 'pdf'"),
            sqlite_where=text("file_type = 'pdf'"),
        ),
        Index(
            "uq_documents_parent_csv",
            "parent_document_id",
            unique=True,
            postgresql_where=text("file_type = 'csv'"),
            sqlite_where=text("file_type = 'csv'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    processing_error: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SourceLocationRow(Base):
    """Normalized source anchor shared by claims and evidence chunks."""

    __tablename__ = "source_locations"
    __table_args__ = (
        UniqueConstraint("document_id", "anchor_id", name="uq_source_location_document_anchor"),
        UniqueConstraint("id", "document_id", name="uq_source_location_id_document_id"),
        CheckConstraint(
            "kind IN ('paragraph', 'table_row', 'table_cell', 'csv_row')",
            name="ck_source_locations_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anchor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list[float] | None] = mapped_column(JSON_VALUE, nullable=True)
    low_quality: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    low_quality_reasons: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    extraction_method: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(128), nullable=False)


class EvidenceChunkRow(Base):
    """Persist an evidence chunk with a platform ID and the original source chunk ID."""

    __tablename__ = "evidence_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "source_chunk_id", name="uq_evidence_document_source_chunk"
        ),
        UniqueConstraint("document_id", "ordinal", name="uq_evidence_document_ordinal"),
        ForeignKeyConstraint(
            ["source_location_id", "document_id"],
            ["source_locations.id", "source_locations.document_id"],
            name="fk_evidence_chunk_source_location_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model_id IS NULL "
            "AND embedding_model_revision IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model_id IS NOT NULL "
            "AND embedding_model_revision IS NOT NULL)",
            name="ck_evidence_chunks_embedding_metadata",
        ),
        Index(
            "ix_evidence_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_chunk_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_location_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    cells: Mapped[dict[str, str] | None] = mapped_column(JSON_VALUE, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    embedding_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ClaimRow(Base):
    """Persist a document-scoped claim while retaining B's original claim ID."""

    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "claim_type IN ('quantitative', 'comparative', 'temporal', 'citation', "
            "'categorical', 'other')",
            name="ck_claims_type",
        ),
        UniqueConstraint(
            "document_id", "extractor_claim_id", name="uq_claims_document_extractor_id"
        ),
        ForeignKeyConstraint(
            ["source_location_id", "document_id"],
            ["source_locations.id", "source_locations.document_id"],
            name="fk_claims_source_location_document",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    extractor_claim_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_location_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_anchor_id: Mapped[str] = mapped_column(String(256), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    numeric_slots: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(128), nullable=False)
    extraction_confidence: Mapped[float] = mapped_column(nullable=False)
    low_quality: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class AnalysisRunRow(Base):
    """Immutable run metadata; each rerun receives a distinct UUID."""

    __tablename__ = "analysis_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VerificationResultRow(Base):
    """Run-scoped numeric-slot or domain-pack result for a claim."""

    __tablename__ = "verification_results"
    __table_args__ = (
        CheckConstraint(
            "result_type IN ('numeric_slot', 'domain_validator')",
            name="ck_verification_results_type",
        ),
        CheckConstraint(
            "result IN ('match', 'mismatch', 'incomparable', 'not_applicable')",
            name="ck_verification_results_result",
        ),
        UniqueConstraint(
            "run_id", "claim_id", "result_type", "result_key", name="uq_verification_result_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    result_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    validator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    slot_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assumptions: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    trace: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)


class VerificationEvidenceRow(Base):
    """Evidence association for aggregate validators that consume several chunks."""

    __tablename__ = "verification_evidence"
    verification_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_results.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_chunks.id", ondelete="RESTRICT"), primary_key=True
    )


class NumericCheckRow(Base):
    """Per-evidence numeric check linked to its parent result and evidence chunk."""

    __tablename__ = "numeric_checks"
    __table_args__ = (
        CheckConstraint(
            "result IN ('match', 'mismatch', 'incomparable', 'not_applicable')",
            name="ck_numeric_checks_result",
        ),
        UniqueConstraint(
            "verification_result_id", "check_index", name="uq_numeric_check_result_index"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    verification_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_chunks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    check_index: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    claim_slots: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    evidence_slots: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    tolerance: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(ExactDecimal(), nullable=True)
    failed_slots: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    trace: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    validator_version: Mapped[str] = mapped_column(String(128), nullable=False)


class NLIResultRow(Base):
    """Run-scoped NLI class distribution attached to one persisted evidence chunk."""

    __tablename__ = "nli_results"
    __table_args__ = (
        CheckConstraint(
            "label IN ('entailment', 'contradiction', 'neutral')",
            name="ck_nli_results_label",
        ),
        CheckConstraint(
            "contradiction_score >= 0 AND contradiction_score <= 1 AND "
            "entailment_score >= 0 AND entailment_score <= 1 AND "
            "neutral_score >= 0 AND neutral_score <= 1",
            name="ck_nli_results_score_range",
        ),
        UniqueConstraint(
            "run_id", "claim_id", "evidence_chunk_id", name="uq_nli_result_pair"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evidence_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_chunks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    contradiction_score: Mapped[float] = mapped_column(Float, nullable=False)
    entailment_score: Mapped[float] = mapped_column(Float, nullable=False)
    neutral_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)


class RerankerResultRow(Base):
    """Run-scoped relevance score attached to one retrieved claim-evidence pair."""

    __tablename__ = "reranker_results"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_reranker_results_score_range",
        ),
        UniqueConstraint(
            "run_id", "claim_id", "evidence_chunk_id", name="uq_reranker_result_pair"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evidence_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_chunks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(64), nullable=False)


class VerdictRow(Base):
    """Immutable final policy outcome for a claim in one analysis run."""

    __tablename__ = "verdicts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Supported', 'Partially Supported', 'Contradicted', "
            "'Unsupported', 'Needs Review')",
            name="ck_verdicts_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_verdicts_confidence_range",
        ),
        UniqueConstraint("run_id", "claim_id", name="uq_verdict_run_claim"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False, default=list)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)


class VerdictEvidenceRow(Base):
    """Provenance links from final verdicts to every retrieved source chunk."""

    __tablename__ = "verdict_evidence"

    verdict_id: Mapped[UUID] = mapped_column(
        ForeignKey("verdicts.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence_chunks.id", ondelete="RESTRICT"), primary_key=True
    )

class WorkspaceReviewRow(Base):
    """Append-only review of an immutable engineering verdict."""

    __tablename__ = "workspace_reviews"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    verdict_id: Mapped[UUID] = mapped_column(ForeignKey("verdicts.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(255))
    override_verdict: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text)
    flag_for_rerun: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
