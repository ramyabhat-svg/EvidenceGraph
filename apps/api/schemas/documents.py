"""Stable API response models for document intake and analysis results."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class DocumentIntakeResponse(BaseModel):
    """Acknowledgement returned after a document is stored and queued."""

    document_id: UUID
    file_document_id: UUID
    project_id: UUID
    file_type: Literal["pdf", "csv"]
    status: Literal["queued"]
    parent_document_id: UUID | None


class DocumentFileStatusResponse(BaseModel):
    """Queue or processing state for one physical PDF or CSV file row."""

    file_document_id: UUID
    file_type: Literal["pdf", "csv"]
    status: Literal["queued", "processing", "complete", "error"]
    processing_error: str | None


class DocumentStatusResponse(BaseModel):
    """Current worker processing state for one stored document."""

    document_id: UUID
    project_id: UUID
    status: Literal["queued", "processing", "complete", "error"]
    processing_error: str | None
    analysis_run_ids: list[UUID]
    files: list[DocumentFileStatusResponse]


class EvidenceProvenanceResponse(BaseModel):
    """Persisted source identity and location for evidence used by a verdict."""

    evidence_chunk_id: UUID
    source_chunk_id: UUID
    document_id: UUID
    anchor_id: str
    kind: str
    page: int | None
    table_index: int | None
    row: int | None
    col: int | None
    char_start: int | None
    char_end: int | None
    bbox: tuple[float, float, float, float] | None
    low_quality: bool
    low_quality_reasons: list[str]


class NumericEvidenceCheckResponse(BaseModel):
    """One numeric comparison with exact decimal values represented as strings."""

    evidence_chunk_id: UUID
    result: str
    claim_slots: dict[str, Any]
    evidence_slots: dict[str, Any]
    tolerance: str | None
    difference: str | None
    failed_slots: list[str]
    trace: list[str]
    validator_version: str


class NumericVerificationResponse(BaseModel):
    """Persisted result for one claim numeric slot."""

    slot_index: int
    result: str
    reason: str | None
    validator: str | None
    checks: list[NumericEvidenceCheckResponse]


class NLIResultResponse(BaseModel):
    """NLI class distribution for one claim-evidence pair."""

    evidence_chunk_id: UUID
    label: str
    contradiction_score: float
    entailment_score: float
    neutral_score: float


class RerankerResultResponse(BaseModel):
    """Locally computed reranker relevance score for one evidence chunk."""

    evidence_chunk_id: UUID
    score: float


class ClaimVerdictResponse(BaseModel):
    """Final policy decision and all persisted support used to produce it."""

    claim_id: UUID
    status: str
    confidence: float | None
    reason: str
    explanation: list[str]
    policy_version: str
    numeric_verifications: list[NumericVerificationResponse]
    nli_results: list[NLIResultResponse]
    reranker_results: list[RerankerResultResponse]
    evidence: list[EvidenceProvenanceResponse]


class AnalysisRunVerdictsResponse(BaseModel):
    """All verdict outputs persisted for one analysis run."""

    analysis_run_id: UUID
    document_id: UUID
    verdicts: list[ClaimVerdictResponse]
