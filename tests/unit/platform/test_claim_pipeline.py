"""Tests for claim extraction and persistence in the document worker flow."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import AnchorKind, Claim, EvidenceChunk, IngestionResult, SourceAnchor
from eg_common.ids import derive_uuid
from persistence.models import Base, ClaimRow, DocumentRow, EvidenceChunkRow, VerdictRow
from persistence.repositories import PersistenceRepository
from worker.orchestration import claims, ingestion


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated SQLite database for one claim pipeline test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _chunk(document_id: UUID) -> EvidenceChunk:
    """Build a paragraph evidence item containing one extractable metric claim."""
    anchor = SourceAnchor(
        anchor_id="paperhash:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=35,
        extraction_method="test-pdf-parser",
        parser_version="test-pdf-v1",
    )
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text="The model achieves 91.2% accuracy.",
    )


def _create_document(
    session: Session, document_id: UUID, file_hash: str, storage_path: str = "paper.pdf"
) -> None:
    """Create the project and PDF document needed by the worker pipeline."""
    repository = PersistenceRepository(session)
    project_id = uuid4()
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="paper.pdf",
        file_hash=file_hash,
        storage_path=storage_path,
        file_type="pdf",
    )


class FakeEmbeddingService:
    """Return deterministic vectors without loading model artifacts."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one valid 384-dimensional vector per text."""
        return [[1.0] + [0.0] * 383 for _ in texts]


def test_claims_are_extracted_from_persisted_chunks_and_retries_are_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    """B's extracted claims retain source links and stable platform IDs across retries."""
    document_id = uuid4()
    file_hash = "a" * 64
    source_chunk = _chunk(document_id)

    with session_factory() as session, session.begin():
        _create_document(session, document_id, file_hash)
        repository = PersistenceRepository(session)
        repository.store_ingestion_result(
            document_id, IngestionResult(chunks=[source_chunk])
        )

        first = claims.extract_and_persist_claims(session, document_id)
        retry = claims.extract_and_persist_claims(session, document_id)

        assert first
        assert retry == first
        assert first[0].claim_text == "The model achieves 91.2% accuracy."
        assert first[0].source_anchor_id == source_chunk.anchor.anchor_id
        expected_id = derive_uuid(
            document_id,
            first[0].source_anchor_id,
            first[0].char_start,
            first[0].char_end,
        )
        row = session.get(ClaimRow, expected_id)
        assert row is not None
        assert row.document_id == document_id
        assert row.source_location_id == derive_uuid(
            document_id, "source_location", source_chunk.anchor.anchor_id
        )
        evidence_row = session.scalar(
            select(EvidenceChunkRow).where(
                EvidenceChunkRow.document_id == document_id,
                EvidenceChunkRow.source_chunk_id == source_chunk.chunk_id,
            )
        )
        assert evidence_row is not None
        assert row.source_location_id == evidence_row.source_location_id
        assert row.extractor_claim_id == first[0].claim_id
        assert session.scalar(
            select(ClaimRow.id).where(ClaimRow.document_id == document_id)
        ) == expected_id
        persisted_rows = session.scalars(
            select(ClaimRow).where(ClaimRow.document_id == document_id)
        ).all()
        assert len(persisted_rows) == 1

    with session_factory() as session:
        restored = PersistenceRepository(session).get_claim(expected_id)
        assert restored == first[0]


def test_worker_runs_claim_extraction_after_ingestion_and_retries_without_duplicates(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The queued-document flow invokes B's extractor after it stores parser output."""
    document_id = uuid4()
    file_hash = "b" * 64
    source_chunk = _chunk(document_id)

    def parse_pdf(_path: Path, target_id: UUID, target_hash: str) -> list[EvidenceChunk]:
        assert target_id == document_id
        assert target_hash == file_hash
        return [source_chunk]

    monkeypatch.setattr(ingestion, "ingest_pdf", parse_pdf)
    with session_factory() as session, session.begin():
        _create_document(session, document_id, file_hash, str(tmp_path / "paper.pdf"))

    embedder = FakeEmbeddingService()
    assert ingestion.process_next_document(session_factory, embedding_service=embedder)
    with session_factory() as session, session.begin():
        document = session.get(DocumentRow, document_id)
        assert document is not None
        assert document.status == "complete"
        document.status = "queued"

    assert ingestion.process_next_document(session_factory, embedding_service=embedder)
    with session_factory() as session:
        stored = session.scalars(select(ClaimRow).where(ClaimRow.document_id == document_id)).all()
        assert len(stored) == 1
        verdicts = session.scalars(
            select(VerdictRow).where(VerdictRow.claim_id == stored[0].id)
        ).all()
        assert len(verdicts) == 1
        assert verdicts[0].status == "Needs Review"
        assert verdicts[0].reason == "threshold_unavailable:tau_ext"


def test_claim_extraction_failure_marks_document_with_safe_error_code(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extractor failures are recorded without storing claims or exposing exception text."""
    document_id = uuid4()
    source_chunk = _chunk(document_id)

    def parse_pdf(_path: Path, _target_id: UUID, _target_hash: str) -> list[EvidenceChunk]:
        return [source_chunk]

    def fail_extract(_chunks: list[EvidenceChunk], _file_hash: str) -> list[Claim]:
        raise RuntimeError("private claim text")

    monkeypatch.setattr(ingestion, "ingest_pdf", parse_pdf)
    monkeypatch.setattr(claims, "extract_claims", fail_extract)
    with session_factory() as session, session.begin():
        _create_document(session, document_id, "c" * 64, str(tmp_path / "paper.pdf"))

    with pytest.raises(RuntimeError, match="private claim text"):
        ingestion.process_next_document(session_factory, embedding_service=FakeEmbeddingService())

    with session_factory() as session:
        document = session.get(DocumentRow, document_id)
        assert document is not None
        assert document.status == "error"
        assert document.processing_error == "claim_extraction_failed"
        claims_for_document = session.scalars(
            select(ClaimRow).where(ClaimRow.document_id == document_id)
        ).all()
        assert claims_for_document == []
