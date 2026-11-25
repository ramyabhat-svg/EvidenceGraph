"""Dispatch file ingestion and persist its source provenance."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased, sessionmaker

from domain.schemas import IngestionResult
from eg_common.logging import log_event
from persistence.models import DocumentRow
from persistence.repositories import PersistenceNotFoundError, PersistenceRepository
from worker.ingestion.csv_parser import ingest_csv
from worker.ingestion.pdf_parser import ScannedPdfError, ingest_pdf
from worker.orchestration.claims import extract_and_persist_claims
from worker.orchestration.embeddings import EmbeddingService, generate_document_embeddings
from worker.orchestration.nli import NLIService
from worker.orchestration.reranking import EvidenceReranker
from worker.orchestration.semantic_verification import generate_document_verdicts
from worker.orchestration.verification import verify_and_persist_document_claims

_logger = logging.getLogger("evidencegraph.worker.ingestion")


def ingest_document(
    path: Path,
    document_id: UUID,
    file_hash: str,
    file_type: str,
) -> IngestionResult:
    """Dispatch a PDF or CSV to B's parser and return a safe processing error on failure."""
    try:
        if file_type == "pdf":
            chunks = ingest_pdf(path, document_id, file_hash)
        elif file_type == "csv":
            chunks = ingest_csv(path, document_id, file_hash)
        else:
            return IngestionResult(processing_error="unsupported_file_type")
    except ScannedPdfError:
        return IngestionResult(processing_error="scanned_pdf_unsupported")
    except Exception:
        return IngestionResult(processing_error="parse_failed")
    return IngestionResult(chunks=chunks)


def register_document(
    session: Session,
    *,
    project_id: UUID,
    document_id: UUID,
    filename: str,
    file_hash: str,
    storage_path: str,
    file_type: str,
    parent_document_id: UUID | None = None,
) -> DocumentRow:
    """Persist a project and uploaded file using the persistence repository."""
    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    return repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename=filename,
        file_hash=file_hash,
        storage_path=storage_path,
        file_type=file_type,
        parent_document_id=parent_document_id,
    )


def persist_document_ingestion(session: Session, document_id: UUID) -> IngestionResult:
    """Ingest one stored document and persist chunks and source locations idempotently."""
    document = session.get(DocumentRow, document_id)
    if document is None:
        raise PersistenceNotFoundError(f"document {document_id} does not exist")
    result = ingest_document(
        Path(document.storage_path), document.id, document.file_hash, document.file_type
    )
    PersistenceRepository(session).store_ingestion_result(document.id, result)
    document.status = "error" if result.processing_error else "complete"
    session.flush()
    log_event(
        _logger,
        "document_ingestion_finished",
        project_id=str(document.project_id),
        document_id=str(document.id),
        count=len(result.chunks),
        error_code=result.processing_error,
    )
    return result


def process_next_document(
    session_factory: sessionmaker[Session],
    *,
    embedding_service: EmbeddingService | None = None,
    nli_service: NLIService | None = None,
    reranker: EvidenceReranker | None = None,
) -> bool:
    """Claim and process one queued document; return whether work was found."""
    with session_factory() as session, session.begin():
        companion = aliased(DocumentRow)
        unfinished_companion = (
            select(companion.id)
            .where(
                companion.parent_document_id == DocumentRow.id,
                companion.status.in_(("queued", "processing")),
            )
            .exists()
        )
        document = session.scalar(
            select(DocumentRow)
            .where(DocumentRow.status == "queued", ~unfinished_companion)
            .order_by(DocumentRow.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if document is None:
            return False
        document_id = document.id
        document.status = "processing"
        session.flush()

    processing_error = "persistence_failed"
    try:
        with session_factory() as session, session.begin():
            result = persist_document_ingestion(session, document_id)
            if result.processing_error is None:
                processing_error = "embedding_generation_failed"
                generate_document_embeddings(
                    session,
                    document_id,
                    embedding_service=embedding_service,
                )
                processing_error = "claim_extraction_failed"
                extract_and_persist_claims(session, document_id)
                processing_error = "numeric_verification_failed"
                numeric_outputs = verify_and_persist_document_claims(
                    session,
                    document_id,
                    embedding_service=embedding_service,
                )
                processing_error = "semantic_verification_failed"
                generate_document_verdicts(
                    session,
                    document_id,
                    numeric_outputs=numeric_outputs,
                    embedding_service=embedding_service,
                    nli_service=nli_service,
                    reranker=reranker,
                )
    except Exception:
        with session_factory() as session, session.begin():
            document = session.get(DocumentRow, document_id)
            if document is not None and document.status == "processing":
                document.status = "error"
                document.processing_error = processing_error
                session.flush()
        raise
    return True
