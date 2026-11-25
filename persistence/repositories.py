"""Repositories for persistence of source data and verification outputs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from domain.entities import (
    NLIClassification,
    NLILabel,
    PersistedNLIResult,
    PersistedVerdict,
    Verdict,
    VerdictStatus,
)
from domain.schemas import CheckResult, Claim, IngestionResult, NumericCheck, SourceAnchor
from domain_packs.scientific_research.pack import ValidationResult
from eg_common.ids import derive_uuid
from persistence.mappers import (
    claim_from_row,
    claim_values,
    evidence_chunk_from_row,
    evidence_chunk_values,
    numeric_check_from_row,
    numeric_check_values,
    slot_verification_from_rows,
    slot_verification_values,
    source_anchor_from_row,
    source_location_values,
    validation_result_from_row,
    validation_result_values,
)
from persistence.models import (
    AnalysisRunRow,
    Base,
    ClaimRow,
    DocumentRow,
    EvidenceChunkRow,
    NLIResultRow,
    NumericCheckRow,
    ProjectRow,
    RerankerResultRow,
    SourceLocationRow,
    VerdictEvidenceRow,
    VerdictRow,
    VerificationEvidenceRow,
    VerificationResultRow,
)
from worker.verification.numeric import SlotVerification

_Row = TypeVar("_Row", bound=Base)


@dataclass(frozen=True)
class EvidenceEmbeddingInput:
    """Text and source identity needed to generate an evidence embedding."""

    document_id: UUID
    source_chunk_id: UUID
    text: str


@dataclass(frozen=True)
class EvidenceProvenance:
    """Evidence identity and source anchor exposed to downstream API readers."""

    evidence_chunk_id: UUID
    source_chunk_id: UUID
    document_id: UUID
    anchor: SourceAnchor


@dataclass(frozen=True)
class NumericCheckEvidence:
    """One numeric check paired with its persisted evidence identity."""

    evidence_chunk_id: UUID
    check: NumericCheck


@dataclass(frozen=True)
class NumericVerificationRecord:
    """A persisted numeric slot result and its source-linked checks."""

    slot_index: int
    result: CheckResult
    reason: str | None
    validator: str | None
    checks: tuple[NumericCheckEvidence, ...]


class PersistenceNotFoundError(LookupError):
    """A required persisted object does not exist."""


class PersistenceConflictError(ValueError):
    """An immutable persistence identity already has different content."""


class PersistenceContractError(ValueError):
    """An input object violates a persisted relationship contract."""


def _insert_immutable(
    session: Session,
    row_type: type[_Row],
    primary_key: Any,
    values: dict[str, Any],
    label: str,
) -> _Row:
    """Insert once or verify an exact retry of the same immutable value."""
    existing = session.get(row_type, primary_key)
    if existing is not None:
        differences = [name for name, value in values.items() if getattr(existing, name) != value]
        if differences:
            raise PersistenceConflictError(
                f"{label} already exists with different fields: {', '.join(differences)}"
            )
        return existing
    row = row_type(**values)
    session.add(row)
    session.flush()
    return row


class PersistenceRepository:
    """Store and retrieve domain records using a caller-owned SQLAlchemy session.

    Methods flush writes but do not commit. Callers own transaction boundaries.
    """

    def __init__(self, session: Session) -> None:
        """Create a repository bound to one SQLAlchemy session."""
        self._session = session

    def create_project(self, project_id: UUID | None = None) -> ProjectRow:
        """Create a project, or return it when the same ID is retried."""
        resolved_id = project_id or uuid4()
        existing = self._session.get(ProjectRow, resolved_id)
        if existing is not None:
            return existing
        row = ProjectRow(id=resolved_id)
        self._session.add(row)
        self._session.flush()
        return row

    def create_document(
        self,
        *,
        document_id: UUID,
        project_id: UUID,
        filename: str,
        file_hash: str,
        storage_path: str,
        file_type: str,
        parent_document_id: UUID | None = None,
    ) -> DocumentRow:
        """Create a document row and validate the companion CSV relationship."""
        project = self._session.get(ProjectRow, project_id)
        if project is None:
            raise PersistenceNotFoundError(f"project {project_id} does not exist")
        if file_type not in {"pdf", "csv"}:
            raise PersistenceContractError("file_type must be pdf or csv")
        if file_type == "pdf" and parent_document_id is not None:
            raise PersistenceContractError("PDF documents cannot have a parent document")
        if file_type == "csv":
            if parent_document_id is None:
                raise PersistenceContractError("CSV documents require a parent PDF")
            parent = self._session.get(DocumentRow, parent_document_id)
            if parent is None or parent.project_id != project_id or parent.file_type != "pdf":
                raise PersistenceContractError("CSV parent must be a PDF in the same project")
            existing_csv_id = self._session.scalar(
                select(DocumentRow.id).where(
                    DocumentRow.parent_document_id == parent_document_id,
                    DocumentRow.file_type == "csv",
                )
            )
            if existing_csv_id is not None and existing_csv_id != document_id:
                raise PersistenceConflictError("a companion CSV already exists for this PDF")

        values: dict[str, Any] = {
            "id": document_id,
            "project_id": project_id,
            "parent_document_id": parent_document_id,
            "filename": filename,
            "file_hash": file_hash,
            "storage_path": storage_path,
            "file_type": file_type,
            "status": "queued",
            "processing_error": None,
        }
        return _insert_immutable(
            self._session,
            DocumentRow,
            document_id,
            values,
            "document",
        )

    def get_document_files(self, document_id: UUID) -> list[DocumentRow]:
        """Load the PDF API document and any companion CSV when given either file ID."""
        requested = self._session.get(DocumentRow, document_id)
        if requested is None:
            raise PersistenceNotFoundError(f"document {document_id} does not exist")
        api_document_id = requested.parent_document_id or requested.id
        rows = self._session.scalars(
            select(DocumentRow)
            .where(
                (DocumentRow.id == api_document_id)
                | (DocumentRow.parent_document_id == api_document_id)
            )
            .order_by(DocumentRow.file_type, DocumentRow.id)
        )
        return list(rows)

    def store_ingestion_result(
        self,
        document_id: UUID,
        result: IngestionResult,
    ) -> IngestionResult:
        """Persist an ingestion result idempotently and preserve chunk order."""
        document = self._session.get(DocumentRow, document_id)
        if document is None:
            raise PersistenceNotFoundError(f"document {document_id} does not exist")

        existing_chunks = list(
            self._session.scalars(
                select(EvidenceChunkRow)
                .where(EvidenceChunkRow.document_id == document_id)
                .order_by(EvidenceChunkRow.ordinal)
            )
        )
        if existing_chunks:
            current = self.get_ingestion_result(document_id)
            if current != result:
                raise PersistenceConflictError(
                    "ingestion result already exists with different content"
                )
            return current

        for ordinal, chunk in enumerate(result.chunks):
            if chunk.document_id != document_id or chunk.anchor.document_id != document_id:
                raise PersistenceContractError(
                    "all ingestion chunks and anchors must belong to the target document"
                )
            location_values = source_location_values(chunk.anchor)
            location_id = location_values["id"]
            _insert_immutable(
                self._session,
                SourceLocationRow,
                location_id,
                location_values,
                "source location",
            )
            chunk_values = evidence_chunk_values(chunk, location_id, ordinal)
            _insert_immutable(
                self._session,
                EvidenceChunkRow,
                chunk_values["id"],
                chunk_values,
                "evidence chunk",
            )

        document.processing_error = result.processing_error
        self._session.flush()
        return result

    def get_ingestion_result(self, document_id: UUID) -> IngestionResult:
        """Load an ingestion result and reconstruct its original chunk sequence."""
        document = self._session.get(DocumentRow, document_id)
        if document is None:
            raise PersistenceNotFoundError(f"document {document_id} does not exist")
        rows = self._session.scalars(
            select(EvidenceChunkRow)
            .where(EvidenceChunkRow.document_id == document_id)
            .order_by(EvidenceChunkRow.ordinal)
        )
        chunks = []
        for row in rows:
            location = self._session.get(SourceLocationRow, row.source_location_id)
            if location is None:
                raise PersistenceContractError("evidence chunk has no source location")
            anchor = source_anchor_from_row(location)
            chunks.append(evidence_chunk_from_row(row, anchor))
        return IngestionResult(chunks=chunks, processing_error=document.processing_error)

    def list_evidence_provenance(
        self,
        evidence_chunk_ids: Sequence[UUID],
    ) -> list[EvidenceProvenance]:
        """Load source anchors for the requested persisted evidence IDs."""
        unique_ids = tuple(dict.fromkeys(evidence_chunk_ids))
        if not unique_ids:
            return []
        rows = self._session.execute(
            select(EvidenceChunkRow, SourceLocationRow)
            .join(
                SourceLocationRow,
                (SourceLocationRow.id == EvidenceChunkRow.source_location_id)
                & (SourceLocationRow.document_id == EvidenceChunkRow.document_id),
            )
            .where(EvidenceChunkRow.id.in_(unique_ids))
            .order_by(EvidenceChunkRow.id)
        )
        provenance = [
            EvidenceProvenance(
                evidence_chunk_id=evidence.id,
                source_chunk_id=evidence.source_chunk_id,
                document_id=evidence.document_id,
                anchor=source_anchor_from_row(location),
            )
            for evidence, location in rows
        ]
        found_ids = {item.evidence_chunk_id for item in provenance}
        if found_ids != set(unique_ids):
            raise PersistenceNotFoundError("one or more evidence chunks do not exist")
        return provenance

    def list_chunks_needing_embeddings(
        self,
        *,
        model_id: str,
        model_revision: str,
        limit: int,
        document_id: UUID | None = None,
    ) -> list[EvidenceEmbeddingInput]:
        """List complete-document chunks missing embeddings for the requested model revision."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        statement = (
            select(EvidenceChunkRow)
            .join(DocumentRow, DocumentRow.id == EvidenceChunkRow.document_id)
            .where(
                DocumentRow.status == "complete",
                or_(
                    EvidenceChunkRow.embedding.is_(None),
                    EvidenceChunkRow.embedding_model_id != model_id,
                    EvidenceChunkRow.embedding_model_revision != model_revision,
                ),
            )
            .order_by(EvidenceChunkRow.document_id, EvidenceChunkRow.ordinal)
            .limit(limit)
        )
        if document_id is not None:
            statement = statement.where(EvidenceChunkRow.document_id == document_id)
        rows = self._session.scalars(statement)
        return [
            EvidenceEmbeddingInput(
                document_id=row.document_id,
                source_chunk_id=row.source_chunk_id,
                text=row.text,
            )
            for row in rows
        ]

    def store_evidence_embeddings(
        self,
        *,
        document_id: UUID,
        embeddings: Mapping[UUID, Sequence[float]],
        model_id: str,
        model_revision: str,
    ) -> int:
        """Persist validated vectors idempotently by document and source chunk identity."""
        updated = 0
        for source_chunk_id, vector in embeddings.items():
            values = list(vector)
            if len(values) != 384 or any(not math.isfinite(value) for value in values):
                raise PersistenceContractError(
                    "evidence embeddings must contain 384 finite dimensions"
                )
            row = self._session.scalar(
                select(EvidenceChunkRow)
                .where(
                    EvidenceChunkRow.document_id == document_id,
                    EvidenceChunkRow.source_chunk_id == source_chunk_id,
                )
                .with_for_update()
            )
            if row is None:
                raise PersistenceContractError(
                    "embedding source chunk must belong to the target document"
                )
            if (
                row.embedding is not None
                and row.embedding_model_id == model_id
                and row.embedding_model_revision == model_revision
            ):
                continue
            row.embedding = values
            row.embedding_model_id = model_id
            row.embedding_model_revision = model_revision
            updated += 1
        self._session.flush()
        return updated

    def store_claims(self, claims: list[Claim]) -> list[Claim]:
        """Persist claims under document-scoped IDs and retain extractor IDs."""
        stored = []
        for claim in claims:
            location_id = derive_uuid(claim.document_id, "source_location", claim.source_anchor_id)
            location = self._session.get(SourceLocationRow, location_id)
            if location is None or location.document_id != claim.document_id:
                raise PersistenceContractError(
                    "claim source anchor must be stored for the same document"
                )
            values = claim_values(claim, location_id)
            row = _insert_immutable(
                self._session,
                ClaimRow,
                values["id"],
                values,
                "claim",
            )
            stored.append(claim_from_row(row))
        return stored

    def get_claim(self, claim_id: UUID) -> Claim:
        """Load one claim by its document-scoped persistence ID."""
        row = self._session.get(ClaimRow, claim_id)
        if row is None:
            raise PersistenceNotFoundError(f"claim {claim_id} does not exist")
        return claim_from_row(row)

    def list_claims(self, document_id: UUID) -> list[Claim]:
        """Load document claims in source-anchor and offset order."""
        rows = self._session.scalars(
            select(ClaimRow)
            .where(ClaimRow.document_id == document_id)
            .order_by(ClaimRow.source_anchor_id, ClaimRow.char_start, ClaimRow.char_end)
        )
        return [claim_from_row(row) for row in rows]

    def create_analysis_run(
        self,
        *,
        run_id: UUID,
        document_id: UUID,
        configuration: dict[str, Any],
        model_versions: dict[str, Any],
        policy_version: str | None,
    ) -> AnalysisRunRow:
        """Create an immutable run; retries with the same ID must have identical metadata."""
        if self._session.get(DocumentRow, document_id) is None:
            raise PersistenceNotFoundError(f"document {document_id} does not exist")
        values = {
            "id": run_id,
            "document_id": document_id,
            "configuration": configuration,
            "model_versions": model_versions,
            "policy_version": policy_version,
        }
        return _insert_immutable(
            self._session,
            AnalysisRunRow,
            run_id,
            values,
            "analysis run",
        )

    def list_analysis_runs(self, document_id: UUID) -> list[AnalysisRunRow]:
        """Load a document's persisted analysis runs in stable creation order."""
        if self._session.get(DocumentRow, document_id) is None:
            raise PersistenceNotFoundError(f"document {document_id} does not exist")
        rows = self._session.scalars(
            select(AnalysisRunRow)
            .where(AnalysisRunRow.document_id == document_id)
            .order_by(AnalysisRunRow.created_at, AnalysisRunRow.id)
        )
        return list(rows)

    def store_numeric_verifications(
        self,
        *,
        run_id: UUID,
        claim_id: UUID,
        results: list[SlotVerification],
        evidence_persistence_ids: Mapping[UUID, UUID] | Sequence[UUID],
    ) -> None:
        """Persist slot summaries and checks using source IDs or ordered evidence IDs.

        Mapping input preserves the original repository contract. A sequence can disambiguate
        repeated extractor chunk IDs across documents by matching each verifier check's order.
        """
        run, _claim = self._require_run_claim(run_id, claim_id)
        run_document = self._session.get(DocumentRow, run.document_id)
        if run_document is None:
            raise PersistenceContractError("analysis run refers to a missing document")

        for result in results:
            values = slot_verification_values(run_id, claim_id, result)
            row = _insert_immutable(
                self._session,
                VerificationResultRow,
                values["id"],
                values,
                "numeric verification result",
            )
            for check_index, (source_chunk_id, check) in enumerate(result.per_evidence):
                evidence_id = (
                    evidence_persistence_ids.get(source_chunk_id)
                    if isinstance(evidence_persistence_ids, Mapping)
                    else evidence_persistence_ids[check_index]
                    if check_index < len(evidence_persistence_ids)
                    else None
                )
                if evidence_id is None:
                    raise PersistenceContractError(
                        f"no persisted evidence mapping for source chunk {source_chunk_id}"
                    )
                evidence = self._require_project_evidence(evidence_id, run_document.project_id)
                check_values = numeric_check_values(row.id, evidence.id, check_index, check)
                _insert_immutable(
                    self._session,
                    NumericCheckRow,
                    check_values["id"],
                    check_values,
                    "numeric check",
                )
                link_values = {
                    "verification_result_id": row.id,
                    "evidence_chunk_id": evidence.id,
                }
                _insert_immutable(
                    self._session,
                    VerificationEvidenceRow,
                    (row.id, evidence.id),
                    link_values,
                    "verification evidence link",
                )
        self._session.flush()

    def store_pack_validation_results(
        self,
        *,
        run_id: UUID,
        claim_id: UUID,
        results: list[ValidationResult],
        evidence_persistence_ids: list[UUID],
    ) -> None:
        """Persist pack outputs separately and link each to its supplied evidence set."""
        run, _claim = self._require_run_claim(run_id, claim_id)
        run_document = self._session.get(DocumentRow, run.document_id)
        if run_document is None:
            raise PersistenceContractError("analysis run refers to a missing document")
        evidence = [
            self._require_project_evidence(item, run_document.project_id)
            for item in evidence_persistence_ids
        ]

        for index, result in enumerate(results):
            values = validation_result_values(run_id, claim_id, index, result)
            row = _insert_immutable(
                self._session,
                VerificationResultRow,
                values["id"],
                values,
                "domain validation result",
            )
            for chunk in evidence:
                link_values = {
                    "verification_result_id": row.id,
                    "evidence_chunk_id": chunk.id,
                }
                _insert_immutable(
                    self._session,
                    VerificationEvidenceRow,
                    (row.id, chunk.id),
                    link_values,
                    "verification evidence link",
                )
        self._session.flush()

    def store_nli_results(
        self,
        *,
        run_id: UUID,
        claim_id: UUID,
        results: Sequence[PersistedNLIResult],
        model_id: str,
        model_revision: str,
    ) -> None:
        """Persist one NLI distribution per retrieved evidence pair idempotently."""
        run, _claim = self._require_run_claim(run_id, claim_id)
        run_document = self._session.get(DocumentRow, run.document_id)
        if run_document is None:
            raise PersistenceContractError("analysis run refers to a missing document")
        for item in results:
            evidence = self._require_project_evidence(
                item.evidence_chunk_id,
                run_document.project_id,
            )
            classification = item.classification
            scores = (
                classification.contradiction_score,
                classification.entailment_score,
                classification.neutral_score,
            )
            if any(not math.isfinite(score) or not 0 <= score <= 1 for score in scores):
                raise PersistenceContractError(
                    "NLI scores must be finite values between zero and one"
                )
            values = {
                "id": derive_uuid(
                    run_id, claim_id, evidence.id, "nli", model_revision
                ),
                "run_id": run_id,
                "claim_id": claim_id,
                "evidence_chunk_id": evidence.id,
                "label": classification.label.value,
                "contradiction_score": classification.contradiction_score,
                "entailment_score": classification.entailment_score,
                "neutral_score": classification.neutral_score,
                "model_id": model_id,
                "model_revision": model_revision,
            }
            _insert_immutable(
                self._session,
                NLIResultRow,
                values["id"],
                values,
                "NLI result",
            )
        self._session.flush()

    def list_nli_results(self, run_id: UUID, claim_id: UUID) -> list[PersistedNLIResult]:
        """Load NLI distributions with the persisted evidence IDs they classify."""
        rows = self._session.scalars(
            select(NLIResultRow)
            .where(NLIResultRow.run_id == run_id, NLIResultRow.claim_id == claim_id)
            .order_by(NLIResultRow.evidence_chunk_id)
        )
        return [
            PersistedNLIResult(
                evidence_chunk_id=row.evidence_chunk_id,
                classification=NLIClassification(
                    label=NLILabel(row.label),
                    contradiction_score=row.contradiction_score,
                    entailment_score=row.entailment_score,
                    neutral_score=row.neutral_score,
                ),
            )
            for row in rows
        ]

    def store_reranker_results(
        self,
        *,
        run_id: UUID,
        claim_id: UUID,
        results: Sequence[tuple[UUID, float]],
        model_id: str,
        model_revision: str,
    ) -> None:
        """Persist one bounded relevance score per retrieved evidence pair idempotently."""
        run, _claim = self._require_run_claim(run_id, claim_id)
        run_document = self._session.get(DocumentRow, run.document_id)
        if run_document is None:
            raise PersistenceContractError("analysis run refers to a missing document")
        for evidence_id, score in results:
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise PersistenceContractError(
                    "reranker scores must be finite values between zero and one"
                )
            evidence = self._require_project_evidence(evidence_id, run_document.project_id)
            values = {
                "id": derive_uuid(run_id, claim_id, evidence.id, "reranker", model_revision),
                "run_id": run_id,
                "claim_id": claim_id,
                "evidence_chunk_id": evidence.id,
                "score": score,
                "model_id": model_id,
                "model_revision": model_revision,
            }
            _insert_immutable(
                self._session,
                RerankerResultRow,
                values["id"],
                values,
                "reranker result",
            )
        self._session.flush()

    def list_reranker_results(
        self,
        run_id: UUID,
        claim_id: UUID,
    ) -> list[tuple[UUID, float]]:
        """Load run-scoped relevance scores by persisted evidence ID."""
        rows = self._session.scalars(
            select(RerankerResultRow)
            .where(
                RerankerResultRow.run_id == run_id,
                RerankerResultRow.claim_id == claim_id,
            )
            .order_by(RerankerResultRow.evidence_chunk_id)
        )
        return [(row.evidence_chunk_id, row.score) for row in rows]

    def store_verdict(
        self,
        *,
        run_id: UUID,
        claim_id: UUID,
        verdict: Verdict,
        policy_version: str,
        evidence_persistence_ids: Sequence[UUID],
        policy_inputs: dict[str, Any] | None = None,
    ) -> VerdictRow:
        """Persist the final verdict and its complete retrieved evidence provenance."""
        run, _claim = self._require_run_claim(run_id, claim_id)
        run_document = self._session.get(DocumentRow, run.document_id)
        if run_document is None:
            raise PersistenceContractError("analysis run refers to a missing document")
        evidence_rows = [
            self._require_project_evidence(evidence_id, run_document.project_id)
            for evidence_id in dict.fromkeys(evidence_persistence_ids)
        ]
        values = {
            "id": derive_uuid(run_id, claim_id, "verdict", policy_version),
            "run_id": run_id,
            "claim_id": claim_id,
            "status": verdict.status.value,
            "confidence": verdict.confidence,
            "reason": verdict.reason,
            "explanation": list(verdict.explanation),
            "policy_version": policy_version,
            "policy_inputs": policy_inputs,
        }
        row = _insert_immutable(
            self._session,
            VerdictRow,
            values["id"],
            values,
            "claim verdict",
        )
        for evidence in evidence_rows:
            link_values = {
                "verdict_id": row.id,
                "evidence_chunk_id": evidence.id,
            }
            _insert_immutable(
                self._session,
                VerdictEvidenceRow,
                (row.id, evidence.id),
                link_values,
                "verdict evidence link",
            )
        self._session.flush()
        return row

    def list_verdicts(
        self,
        run_id: UUID,
        claim_id: UUID | None = None,
    ) -> list[PersistedVerdict]:
        """Load persisted verdicts and their linked evidence IDs in stable order."""
        if self._session.get(AnalysisRunRow, run_id) is None:
            raise PersistenceNotFoundError(f"analysis run {run_id} does not exist")
        statement = select(VerdictRow).where(VerdictRow.run_id == run_id)
        if claim_id is not None:
            statement = statement.where(VerdictRow.claim_id == claim_id)
        rows = self._session.scalars(statement.order_by(VerdictRow.claim_id))
        verdicts = []
        for row in rows:
            evidence_ids = self._session.scalars(
                select(VerdictEvidenceRow.evidence_chunk_id)
                .where(VerdictEvidenceRow.verdict_id == row.id)
                .order_by(VerdictEvidenceRow.evidence_chunk_id)
            )
            verdicts.append(
                PersistedVerdict(
                    run_id=row.run_id,
                    claim_id=row.claim_id,
                    verdict=Verdict(
                        status=VerdictStatus(row.status),
                        confidence=row.confidence,
                        reason=row.reason,
                        explanation=tuple(row.explanation),
                    ),
                    policy_version=row.policy_version,
                    evidence_chunk_ids=tuple(evidence_ids),
                )
            )
        return verdicts

    def list_numeric_verifications(
        self,
        run_id: UUID,
        claim_id: UUID,
    ) -> list[SlotVerification]:
        """Load numeric slot results and their per-evidence checks."""
        result_rows = self._session.scalars(
            select(VerificationResultRow)
            .where(
                VerificationResultRow.run_id == run_id,
                VerificationResultRow.claim_id == claim_id,
                VerificationResultRow.result_type == "numeric_slot",
            )
            .order_by(VerificationResultRow.slot_index)
        )
        output = []
        for result_row in result_rows:
            check_rows = self._session.scalars(
                select(NumericCheckRow)
                .where(NumericCheckRow.verification_result_id == result_row.id)
                .order_by(NumericCheckRow.check_index)
            )
            details: list[tuple[UUID, NumericCheck]] = []
            for check_row in check_rows:
                evidence = self._session.get(EvidenceChunkRow, check_row.evidence_chunk_id)
                if evidence is None:
                    raise PersistenceContractError("numeric check has no evidence chunk")
                details.append((evidence.source_chunk_id, numeric_check_from_row(check_row)))
            output.append(slot_verification_from_rows(result_row, details))
        return output

    def list_numeric_check_records(
        self,
        run_id: UUID,
        claim_id: UUID,
    ) -> list[NumericVerificationRecord]:
        """Load numeric slot outputs with exact persisted evidence identities."""
        result_rows = self._session.scalars(
            select(VerificationResultRow)
            .where(
                VerificationResultRow.run_id == run_id,
                VerificationResultRow.claim_id == claim_id,
                VerificationResultRow.result_type == "numeric_slot",
            )
            .order_by(VerificationResultRow.slot_index)
        )
        records = []
        for result_row in result_rows:
            check_rows = self._session.scalars(
                select(NumericCheckRow)
                .where(NumericCheckRow.verification_result_id == result_row.id)
                .order_by(NumericCheckRow.check_index)
            )
            checks = tuple(
                NumericCheckEvidence(
                    evidence_chunk_id=row.evidence_chunk_id,
                    check=numeric_check_from_row(row),
                )
                for row in check_rows
            )
            records.append(
                NumericVerificationRecord(
                    slot_index=result_row.slot_index or 0,
                    result=CheckResult(result_row.result),
                    reason=result_row.reason,
                    validator=result_row.validator,
                    checks=checks,
                )
            )
        return records

    def list_pack_validation_results(
        self,
        run_id: UUID,
        claim_id: UUID,
    ) -> list[ValidationResult]:
        """Load pack validation outputs in their persisted order."""
        rows = self._session.scalars(
            select(VerificationResultRow)
            .where(
                VerificationResultRow.run_id == run_id,
                VerificationResultRow.claim_id == claim_id,
                VerificationResultRow.result_type == "domain_validator",
            )
            .order_by(VerificationResultRow.result_key)
        )
        return [validation_result_from_row(row) for row in rows]

    def _require_run_claim(
        self,
        run_id: UUID,
        claim_id: UUID,
    ) -> tuple[AnalysisRunRow, ClaimRow]:
        run = self._session.get(AnalysisRunRow, run_id)
        claim = self._session.get(ClaimRow, claim_id)
        if run is None:
            raise PersistenceNotFoundError(f"analysis run {run_id} does not exist")
        if claim is None:
            raise PersistenceNotFoundError(f"claim {claim_id} does not exist")
        if run.document_id != claim.document_id:
            raise PersistenceContractError(
                "analysis run and claim must belong to the same document"
            )
        return run, claim

    def _require_project_evidence(
        self,
        evidence_id: UUID,
        project_id: UUID,
    ) -> EvidenceChunkRow:
        evidence = self._session.get(EvidenceChunkRow, evidence_id)
        if evidence is None:
            raise PersistenceNotFoundError(f"evidence chunk {evidence_id} does not exist")
        document = self._session.get(DocumentRow, evidence.document_id)
        if document is None or document.project_id != project_id:
            raise PersistenceContractError("verification evidence must belong to the run's project")
        return evidence
