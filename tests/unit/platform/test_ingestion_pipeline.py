"""Tests for parser dispatch, source persistence, and worker error handling."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import AnchorKind, EvidenceChunk, SourceAnchor
from persistence.models import Base, DocumentRow, EvidenceChunkRow, ProjectRow, SourceLocationRow
from worker.ingestion.pdf_parser import ScannedPdfError
from worker.orchestration import ingestion


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated SQLite database for one ingestion test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _chunk(document_id: UUID) -> EvidenceChunk:
    anchor = SourceAnchor(
        anchor_id="hash:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=14,
        extraction_method="pdf-test",
        parser_version="pdf-test-v1",
    )
    return EvidenceChunk(
        chunk_id=uuid4(), document_id=document_id, anchor=anchor, text="Evidence text."
    )


class FakeEmbeddingService:
    """Return deterministic vectors without loading model artifacts."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one valid 384-dimensional vector per text."""
        return [[1.0] + [0.0] * 383 for _ in texts]


def test_csv_dispatch_persists_project_document_and_sources(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """CSV parser output is stored with its original chunk and anchor identities."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("metric,value\naccuracy,0.91\n", encoding="utf-8")
    project_id, document_id = uuid4(), uuid4()
    parent_document_id = uuid4()

    with session_factory() as session, session.begin():
        repository = ingestion.PersistenceRepository(session)
        repository.create_project(project_id)
        repository.create_document(
            document_id=parent_document_id,
            project_id=project_id,
            filename="paper.pdf",
            file_hash="e" * 64,
            storage_path="paper.pdf",
            file_type="pdf",
        )
        ingestion.register_document(
            session,
            project_id=project_id,
            document_id=document_id,
            filename="data.csv",
            file_hash="a" * 64,
            storage_path=str(csv_path),
            file_type="csv",
            parent_document_id=parent_document_id,
        )

    with session_factory() as session, session.begin():
        result = ingestion.ingest_document(csv_path, document_id, "a" * 64, "csv")
        assert len(result.chunks) == 1
        assert result.chunks[0].anchor.kind == AnchorKind.CSV_ROW
        ingestion.PersistenceRepository(session).store_ingestion_result(document_id, result)

    with session_factory() as session:
        assert session.get(ProjectRow, project_id) is not None
        assert session.get(EvidenceChunkRow, result.chunks[0].chunk_id) is None
        stored = session.query(EvidenceChunkRow).one()
        source = session.get(SourceLocationRow, stored.source_location_id)
        assert source is not None
        assert stored.source_chunk_id == result.chunks[0].chunk_id
        assert source.anchor_id == result.chunks[0].anchor.anchor_id
        assert stored.text == result.chunks[0].text


def test_pdf_dispatch_uses_parser_chunks_and_preserves_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PDF dispatch returns B's chunk models without changing their source IDs."""
    document_id = uuid4()
    chunk = _chunk(document_id)
    calls: list[tuple[Path, UUID, str]] = []

    def parse_pdf(path: Path, target_id: UUID, file_hash: str) -> list[EvidenceChunk]:
        calls.append((path, target_id, file_hash))
        return [chunk]

    monkeypatch.setattr(ingestion, "ingest_pdf", parse_pdf)
    result = ingestion.ingest_document(tmp_path / "paper.pdf", document_id, "b" * 64, "pdf")

    assert result.chunks == [chunk]
    assert calls == [(tmp_path / "paper.pdf", document_id, "b" * 64)]


@pytest.mark.parametrize(
    ("error", "error_code"),
    [(ScannedPdfError(), "scanned_pdf_unsupported"), (OSError("bad file"), "parse_failed")],
)
def test_pdf_parse_errors_become_safe_persistable_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
    error_code: str,
) -> None:
    """Parser failures become stable codes and do not escape into the worker loop."""
    def fail_pdf(_path: Path, _document_id: UUID, _file_hash: str) -> list[EvidenceChunk]:
        raise error

    monkeypatch.setattr(ingestion, "ingest_pdf", fail_pdf)
    result = ingestion.ingest_document(tmp_path / "paper.pdf", uuid4(), "c" * 64, "pdf")

    assert result.processing_error == error_code
    assert result.chunks == []


def test_worker_processes_one_queued_document_and_persists_csv_chunks(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """The worker claims a queued document and persists its ingestion result."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("metric,value\nrecall,0.8\n", encoding="utf-8")
    project_id, document_id = uuid4(), uuid4()
    parent_document_id = uuid4()

    with session_factory() as session, session.begin():
        repository = ingestion.PersistenceRepository(session)
        repository.create_project(project_id)
        repository.create_document(
            document_id=parent_document_id,
            project_id=project_id,
            filename="paper.pdf",
            file_hash="f" * 64,
            storage_path="paper.pdf",
            file_type="pdf",
        )
        parent = session.get(DocumentRow, parent_document_id)
        assert parent is not None
        parent.status = "complete"
        repository.create_document(
            document_id=document_id,
            project_id=project_id,
            filename="data.csv",
            file_hash="d" * 64,
            storage_path=str(csv_path),
            file_type="csv",
            parent_document_id=parent_document_id,
        )

    embedder = FakeEmbeddingService()
    assert ingestion.process_next_document(
        session_factory, embedding_service=embedder
    ) is True
    assert ingestion.process_next_document(
        session_factory, embedding_service=embedder
    ) is False

    with session_factory() as session:
        document = session.get(DocumentRow, document_id)
        assert document is not None
        assert document.status == "complete"
        result = ingestion.PersistenceRepository(session).get_ingestion_result(document_id)
        assert len(result.chunks) == 1


def test_worker_marks_document_failed_when_persistence_raises(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected persistence failures leave a safe error code on the claimed document."""
    project_id, document_id = uuid4(), uuid4()
    with session_factory() as session, session.begin():
        repository = ingestion.PersistenceRepository(session)
        repository.create_project(project_id)
        repository.create_document(
            document_id=document_id,
            project_id=project_id,
            filename="paper.pdf",
            file_hash="1" * 64,
            storage_path="paper.pdf",
            file_type="pdf",
        )

    def fail_persist(_session: Session, _document_id: UUID) -> None:
        raise RuntimeError("private parser or document detail")

    monkeypatch.setattr(ingestion, "persist_document_ingestion", fail_persist)
    with pytest.raises(RuntimeError, match="private parser"):
        ingestion.process_next_document(session_factory)

    with session_factory() as session:
        document = session.get(DocumentRow, document_id)
        assert document is not None
        assert document.status == "error"
        assert document.processing_error == "persistence_failed"
