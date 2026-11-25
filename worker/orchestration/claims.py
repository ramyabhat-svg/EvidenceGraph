"""Extract claims from persisted evidence and store their provenance."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from domain.schemas import Claim
from persistence.models import DocumentRow
from persistence.repositories import (
    PersistenceContractError,
    PersistenceNotFoundError,
    PersistenceRepository,
)
from worker.extraction.claims import extract_claims


def extract_and_persist_claims(session: Session, document_id: UUID) -> list[Claim]:
    """Run B's extractor on persisted chunks and idempotently store document claims."""
    document = session.get(DocumentRow, document_id)
    if document is None:
        raise PersistenceNotFoundError(f"document {document_id} does not exist")

    repository = PersistenceRepository(session)
    ingestion_result = repository.get_ingestion_result(document_id)
    if ingestion_result.processing_error is not None:
        return []

    claims = extract_claims(ingestion_result.chunks, document.file_hash)
    source_anchors = {chunk.anchor.anchor_id for chunk in ingestion_result.chunks}
    for claim in claims:
        if claim.document_id != document_id or claim.source_anchor_id not in source_anchors:
            raise PersistenceContractError(
                "extracted claim must reference an evidence anchor in the same document"
            )
    return repository.store_claims(claims)
