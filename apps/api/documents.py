"""Document intake, processing status, and analysis-result API routes."""

from __future__ import annotations

import codecs
import hashlib
import logging
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.schemas.documents import (
    AnalysisRunVerdictsResponse,
    ClaimVerdictResponse,
    DocumentFileStatusResponse,
    DocumentIntakeResponse,
    DocumentStatusResponse,
    EvidenceProvenanceResponse,
    NLIResultResponse,
    NumericEvidenceCheckResponse,
    NumericVerificationResponse,
    RerankerResultResponse,
)
from apps.api.schemas.errors import ErrorResponse
from domain.entities import PersistedNLIResult, PersistedVerdict
from domain.schemas import NumericSlots
from eg_common.errors import AppError, ConflictError, NotFoundError
from eg_common.logging import log_event
from eg_common.settings import Settings
from persistence.models import AnalysisRunRow, DocumentRow, ProjectRow
from persistence.repositories import (
    EvidenceProvenance,
    NumericVerificationRecord,
    PersistenceConflictError,
    PersistenceContractError,
    PersistenceNotFoundError,
    PersistenceRepository,
)

_logger = logging.getLogger("evidencegraph.api.documents")
_UPLOAD_BLOCK_SIZE = 64 * 1024
_PDF_HEADER_WINDOW = 1024


def create_document_router(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> APIRouter:
    """Build API routes bound to the configured durable storage and database."""
    router = APIRouter()

    @router.post(
        "/projects/{project_id}/documents",
        response_model=DocumentIntakeResponse,
        status_code=202,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid upload request."},
            404: {"model": ErrorResponse, "description": "Project not found."},
            409: {"model": ErrorResponse, "description": "Upload conflicts with project state."},
            413: {"model": ErrorResponse, "description": "Upload exceeds configured size."},
            500: {"model": ErrorResponse, "description": "Unexpected server error."},
            503: {"model": ErrorResponse, "description": "Persistent storage unavailable."},
        },
        name="upload_document",
    )
    def upload_document(
        project_id: UUID,
        file: UploadFile = File(...),
        parent_document_id: UUID | None = Form(default=None),
    ) -> DocumentIntakeResponse:
        """Store one PDF or companion CSV and enqueue it for asynchronous processing."""
        filename = file.filename
        if not filename or len(filename) > 512:
            raise AppError("invalid_filename", "A valid filename is required.", "file")
        file_type = _file_type(filename)
        if file_type == "csv" and parent_document_id is None:
            raise AppError(
                "parent_document_required",
                "CSV uploads must reference a PDF document in this project.",
                "parent_document_id",
            )
        if file_type == "pdf" and parent_document_id is not None:
            raise AppError(
                "invalid_parent_document",
                "PDF uploads cannot have a parent document.",
                "parent_document_id",
            )

        with session_factory() as session:
            if session.get(ProjectRow, project_id) is None:
                raise NotFoundError("The requested project was not found.")
            if file_type == "csv" and _companion_csv_exists(
                session, parent_document_id
            ):
                raise ConflictError(
                    "companion_csv_exists",
                    "This PDF already has a companion CSV.",
                    "parent_document_id",
                )

        document_id = uuid4()
        stored_path, file_hash = _store_upload(
            file,
            settings=settings,
            project_id=project_id,
            document_id=document_id,
            file_type=file_type,
        )
        try:
            with session_factory() as session, session.begin():
                repository = PersistenceRepository(session)
                if session.get(ProjectRow, project_id) is None:
                    raise PersistenceNotFoundError(f"project {project_id} does not exist")
                repository.create_document(
                    document_id=document_id,
                    project_id=project_id,
                    filename=filename,
                    file_hash=file_hash,
                    storage_path=str(stored_path),
                    file_type=file_type,
                    parent_document_id=parent_document_id,
                )
        except IntegrityError as exc:
            _remove_stored_file(stored_path, project_id)
            if file_type == "pdf" and _pdf_hash_exists(
                session_factory, project_id, file_hash
            ):
                raise ConflictError(
                    "duplicate_document",
                    "A PDF with this content already exists in the project.",
                    "file",
                ) from exc
            if file_type == "csv" and _csv_parent_id_exists(
                session_factory, parent_document_id
            ):
                raise ConflictError(
                    "companion_csv_exists",
                    "This PDF already has a companion CSV.",
                    "parent_document_id",
                ) from exc
            raise ConflictError(
                "document_conflict",
                "The document conflicts with an existing project record.",
            ) from exc
        except PersistenceNotFoundError as exc:
            _remove_stored_file(stored_path, project_id)
            raise NotFoundError("The requested project was not found.") from exc
        except PersistenceContractError as exc:
            _remove_stored_file(stored_path, project_id)
            raise AppError(
                "invalid_parent_document",
                "The CSV parent must be a PDF in this project.",
                "parent_document_id",
            ) from exc
        except PersistenceConflictError as exc:
            _remove_stored_file(stored_path, project_id)
            raise ConflictError(
                "companion_csv_exists",
                "This PDF already has a companion CSV.",
                "parent_document_id",
            ) from exc
        except Exception:
            _remove_stored_file(stored_path, project_id)
            raise

        log_event(
            _logger,
            "document_upload_queued",
            project_id=project_id,
            document_id=document_id,
            count=1,
        )
        return DocumentIntakeResponse(
            document_id=parent_document_id or document_id,
            file_document_id=document_id,
            project_id=project_id,
            file_type=file_type,
            status="queued",
            parent_document_id=parent_document_id,
        )

    @router.get(
        "/documents/{document_id}",
        response_model=DocumentStatusResponse,
        responses={
            404: {"model": ErrorResponse, "description": "Document not found."},
            500: {"model": ErrorResponse, "description": "Unexpected server error."},
        },
        name="get_document_status",
    )
    def get_document_status(document_id: UUID) -> DocumentStatusResponse:
        """Return the current queue or processing state and any persisted run IDs."""
        with session_factory() as session:
            repository = PersistenceRepository(session)
            try:
                files = repository.get_document_files(document_id)
            except PersistenceNotFoundError as exc:
                raise NotFoundError("The requested document was not found.") from exc
            api_document_id = next(
                row.id for row in files if row.file_type == "pdf"
            )
            ordered_files = sorted(files, key=lambda row: (row.file_type != "pdf", str(row.id)))
            if any(row.status == "error" for row in ordered_files):
                overall_status = "error"
            elif any(row.status == "processing" for row in ordered_files):
                overall_status = "processing"
            elif any(row.status == "queued" for row in ordered_files):
                overall_status = "queued"
            else:
                overall_status = "complete"
            processing_error = next(
                (row.processing_error for row in ordered_files if row.status == "error"),
                None,
            )
            runs = repository.list_analysis_runs(api_document_id)
            return DocumentStatusResponse(
                document_id=api_document_id,
                project_id=files[0].project_id,
                status=cast(
                    Literal["queued", "processing", "complete", "error"], overall_status
                ),
                processing_error=processing_error,
                analysis_run_ids=[run.id for run in runs],
                files=[
                    DocumentFileStatusResponse(
                        file_document_id=row.id,
                        file_type=cast(Literal["pdf", "csv"], row.file_type),
                        status=cast(
                            Literal["queued", "processing", "complete", "error"], row.status
                        ),
                        processing_error=row.processing_error,
                    )
                    for row in ordered_files
                ],
            )

    @router.get("/workspace/analysis-runs/{run_id}/verdicts", include_in_schema=False)
    @router.get(
        "/analysis-runs/{run_id}/verdicts",
        response_model=AnalysisRunVerdictsResponse,
        responses={
            404: {"model": ErrorResponse, "description": "Analysis run not found."},
            500: {"model": ErrorResponse, "description": "Unexpected server error."},
        },
        name="get_analysis_run_verdicts",
    )
    def get_analysis_run_verdicts(run_id: UUID) -> AnalysisRunVerdictsResponse:
        """Return verdicts, scores, numeric checks, explanations, and source provenance."""
        with session_factory() as session:
            run = session.get(AnalysisRunRow, run_id)
            if run is None:
                raise NotFoundError("The requested analysis run was not found.")
            repository = PersistenceRepository(session)
            verdicts = repository.list_verdicts(run_id)
            output: list[ClaimVerdictResponse] = []
            for persisted in verdicts:
                claim_id = persisted.claim_id
                nli_results = repository.list_nli_results(run_id, claim_id)
                reranker_results = repository.list_reranker_results(run_id, claim_id)
                numeric_records = repository.list_numeric_check_records(run_id, claim_id)
                evidence_ids = list(persisted.evidence_chunk_ids)
                evidence_ids.extend(item.evidence_chunk_id for item in nli_results)
                evidence_ids.extend(evidence_id for evidence_id, _score in reranker_results)
                evidence_ids.extend(
                    check.evidence_chunk_id
                    for record in numeric_records
                    for check in record.checks
                )
                provenance = repository.list_evidence_provenance(evidence_ids)
                output.append(
                    _verdict_response(
                        persisted,
                        nli_results=nli_results,
                        reranker_results=reranker_results,
                        numeric_records=numeric_records,
                        evidence=provenance,
                    )
                )
            return AnalysisRunVerdictsResponse(
                analysis_run_id=run_id,
                document_id=run.document_id,
                verdicts=output,
            )

    return router


def _file_type(filename: str) -> Literal["pdf", "csv"]:
    """Resolve supported file types from the submitted filename extension."""
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".csv":
        return "csv"
    raise AppError("invalid_file_type", "Only PDF and CSV files are accepted.", "file")


def _store_upload(
    upload: UploadFile,
    *,
    settings: Settings,
    project_id: UUID,
    document_id: UUID,
    file_type: Literal["pdf", "csv"],
) -> tuple[Path, str]:
    """Validate and atomically place an upload under the persistent shared storage root."""
    maximum_size = (
        settings.max_pdf_mb if file_type == "pdf" else settings.max_csv_mb
    ) * 1024 * 1024
    root = settings.storage_root.expanduser().resolve()
    project_directory = root / str(project_id)
    final_path = project_directory / f"{document_id}.{file_type}"
    temporary_path: Path | None = None
    digest = hashlib.sha256()
    total_size = 0
    prefix = bytearray()
    decoder = codecs.getincrementaldecoder("utf-8-sig")() if file_type == "csv" else None

    try:
        project_directory.mkdir(parents=True, exist_ok=True)
        if root not in project_directory.resolve().parents:
            raise OSError("configured storage path escaped its root")
        upload.file.seek(0)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=project_directory,
            prefix=f".{document_id}.",
            suffix=".uploading",
            delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            while True:
                block = upload.file.read(_UPLOAD_BLOCK_SIZE)
                if not block:
                    break
                total_size += len(block)
                if total_size > maximum_size:
                    raise AppError(
                        "file_too_large",
                        "The uploaded file exceeds its size limit.",
                        "file",
                        413,
                    )
                if len(prefix) < _PDF_HEADER_WINDOW:
                    prefix.extend(block[: _PDF_HEADER_WINDOW - len(prefix)])
                if decoder is not None:
                    try:
                        decoder.decode(block)
                    except UnicodeDecodeError as exc:
                        raise AppError(
                            "invalid_file_content",
                            "The CSV file must use UTF-8 text encoding.",
                            "file",
                        ) from exc
                digest.update(block)
                destination.write(block)
            if decoder is not None:
                try:
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise AppError(
                        "invalid_file_content",
                        "The CSV file must use UTF-8 text encoding.",
                        "file",
                    ) from exc
            destination.flush()
            os.fsync(destination.fileno())

        if total_size == 0:
            raise AppError("invalid_file_content", "The uploaded file is empty.", "file")
        if file_type == "pdf" and b"%PDF-" not in prefix:
            raise AppError(
                "invalid_file_content",
                "The uploaded file does not contain a PDF header.",
                "file",
            )
        os.replace(temporary_path, final_path)
        temporary_path = None
        return final_path, digest.hexdigest()
    except AppError:
        if temporary_path is not None:
            _remove_stored_file(temporary_path, project_id)
        raise
    except OSError as exc:
        if temporary_path is not None:
            _remove_stored_file(temporary_path, project_id)
        log_event(
            _logger,
            "document_upload_storage_failed",
            project_id=project_id,
            document_id=document_id,
            error_code="storage_unavailable",
            level=logging.ERROR,
        )
        raise AppError(
            "storage_unavailable",
            "Uploaded files cannot be stored right now.",
            http_status=503,
        ) from exc
    except Exception:
        if temporary_path is not None:
            _remove_stored_file(temporary_path, project_id)
        raise


def _remove_stored_file(path: Path, project_id: UUID) -> None:
    """Remove an uncommitted upload and log cleanup failures without exposing paths."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log_event(
            _logger,
            "document_upload_cleanup_failed",
            project_id=project_id,
            error_code="upload_cleanup_failed",
            level=logging.ERROR,
        )


def _pdf_hash_exists(
    session_factory: sessionmaker[Session],
    project_id: UUID,
    file_hash: str,
) -> bool:
    """Check whether a rolled-back PDF upload conflicts with an existing project PDF."""
    with session_factory() as session:
        return (
            session.scalar(
                select(DocumentRow.id).where(
                    DocumentRow.project_id == project_id,
                    DocumentRow.file_hash == file_hash,
                    DocumentRow.file_type == "pdf",
                )
            )
            is not None
        )


def _companion_csv_exists(session: Session, parent_document_id: UUID | None) -> bool:
    """Return whether a parent PDF already has a CSV companion."""
    if parent_document_id is None:
        return False
    return (
        session.scalar(
            select(DocumentRow.id).where(
                DocumentRow.parent_document_id == parent_document_id,
                DocumentRow.file_type == "csv",
            )
        )
        is not None
    )


def _csv_parent_id_exists(
    session_factory: sessionmaker[Session],
    parent_document_id: UUID | None,
) -> bool:
    """Check for a CSV parent collision after rolling back an integrity error."""
    with session_factory() as session:
        return _companion_csv_exists(session, parent_document_id)


def _verdict_response(
    persisted: PersistedVerdict,
    *,
    nli_results: list[PersistedNLIResult],
    reranker_results: list[tuple[UUID, float]],
    numeric_records: list[NumericVerificationRecord],
    evidence: list[EvidenceProvenance],
) -> ClaimVerdictResponse:
    """Convert repository results into a response with exact numeric serialization."""
    numeric = []
    for record in numeric_records:
        checks = []
        for item in record.checks:
            payload = item.check.model_dump(mode="python")
            checks.append(
                NumericEvidenceCheckResponse(
                    evidence_chunk_id=item.evidence_chunk_id,
                    result=payload["result"].value,
                    claim_slots=_numeric_slots_response(item.check.claim_slots),
                    evidence_slots=_numeric_slots_response(item.check.evidence_slots),
                    tolerance=_decimal_string(item.check.tolerance),
                    difference=_decimal_string(item.check.difference),
                    failed_slots=payload["failed_slots"],
                    trace=payload["trace"],
                    validator_version=payload["validator_version"],
                )
            )
        numeric.append(
            NumericVerificationResponse(
                slot_index=record.slot_index,
                result=record.result.value,
                reason=record.reason,
                validator=record.validator,
                checks=checks,
            )
        )

    return ClaimVerdictResponse(
        claim_id=persisted.claim_id,
        status=persisted.verdict.status.value,
        confidence=persisted.verdict.confidence,
        reason=persisted.verdict.reason,
        explanation=list(persisted.verdict.explanation),
        policy_version=persisted.policy_version,
        numeric_verifications=numeric,
        nli_results=[
            NLIResultResponse(
                evidence_chunk_id=item.evidence_chunk_id,
                label=item.classification.label.value,
                contradiction_score=item.classification.contradiction_score,
                entailment_score=item.classification.entailment_score,
                neutral_score=item.classification.neutral_score,
            )
            for item in nli_results
        ],
        reranker_results=[
            RerankerResultResponse(evidence_chunk_id=evidence_id, score=score)
            for evidence_id, score in reranker_results
        ],
        evidence=[
            EvidenceProvenanceResponse(
                evidence_chunk_id=item.evidence_chunk_id,
                source_chunk_id=item.source_chunk_id,
                document_id=item.document_id,
                anchor_id=item.anchor.anchor_id,
                kind=item.anchor.kind.value,
                page=item.anchor.page,
                table_index=item.anchor.table_index,
                row=item.anchor.row,
                col=item.anchor.col,
                char_start=item.anchor.char_start,
                char_end=item.anchor.char_end,
                bbox=item.anchor.bbox,
                low_quality=item.anchor.low_quality,
                low_quality_reasons=item.anchor.low_quality_reasons,
            )
            for item in evidence
        ],
    )


def _numeric_slots_response(slots: NumericSlots) -> dict[str, Any]:
    """Serialize every Decimal slot field as a non-lossy fixed-point string."""
    payload = slots.model_dump(mode="python")
    return {
        key: _decimal_string(value) if isinstance(value, Decimal) else value
        for key, value in payload.items()
    }


def _decimal_string(value: Decimal | None) -> str | None:
    """Render an exact Decimal without converting it to a binary float."""
    return format(value, "f") if value is not None else None
