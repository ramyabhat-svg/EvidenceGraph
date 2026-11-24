"""Tests for local embedding inference, persistence, backfill, and retries."""

import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import AnchorKind, EvidenceChunk, IngestionResult, SourceAnchor
from eg_common.settings import Settings
from persistence.models import Base, DocumentRow, EvidenceChunkRow
from persistence.repositories import PersistenceContractError, PersistenceRepository
from worker.orchestration.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    EmbeddingGenerationError,
    SentenceTransformerEmbeddingService,
    backfill_missing_embeddings,
    generate_document_embeddings,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated SQLite database for embedding tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


class FakeEmbeddingService:
    """Record batches and return deterministic unit vectors without model downloads."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return a unit vector for every input item."""
        self.batches.append(list(texts))
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]


def _make_completed_document(
    session: Session,
) -> tuple[UUID, UUID, list[EvidenceChunk]]:
    """Store a completed PDF and two evidence chunks without their embeddings."""
    project_id, document_id = uuid4(), uuid4()
    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="paper.pdf",
        file_hash=uuid4().hex,
        storage_path="paper.pdf",
        file_type="pdf",
    )
    chunks = []
    for ordinal, text in enumerate(("neural accuracy result", "supporting experiment")):
        anchor = SourceAnchor(
            anchor_id=f"paper:p1:para{ordinal}",
            document_id=document_id,
            kind=AnchorKind.PARAGRAPH,
            page=1,
            char_start=ordinal * 30,
            char_end=ordinal * 30 + len(text),
            extraction_method="test-parser",
            parser_version="test-v1",
        )
        chunks.append(
            EvidenceChunk(
                chunk_id=uuid4(),
                document_id=document_id,
                anchor=anchor,
                text=text,
            )
        )
    repository.store_ingestion_result(document_id, IngestionResult(chunks=chunks))
    document = session.get(DocumentRow, document_id)
    assert document is not None
    document.status = "complete"
    return project_id, document_id, chunks


def test_sentence_transformer_is_pinned_cpu_only_and_testable_without_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader uses the pinned model revision and CPU while encoding is mockable."""
    load_calls = []
    encode_calls = []

    class FakeModel:
        def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
            encode_calls.append((texts, kwargs))
            return [[1.0] + [0.0] * (EMBEDDING_DIMENSION - 1) for _ in texts]

    def fake_model(model_name: str, *, revision: str, device: str) -> FakeModel:
        load_calls.append((model_name, revision, device))
        return FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=fake_model),
    )
    service = SentenceTransformerEmbeddingService(batch_size=3)

    vectors = service.embed_texts(["test text"])

    assert load_calls == [(EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION, "cpu")]
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIMENSION
    assert encode_calls[0][1]["device"] == "cpu"
    assert encode_calls[0][1]["normalize_embeddings"] is True
    assert encode_calls[0][1]["batch_size"] == 3


def test_sentence_transformer_rejects_invalid_vector_shape() -> None:
    """Unexpected model output fails with a controlled embedding error."""

    class BadModel:
        def encode(self, _texts: list[str], **_kwargs: object) -> list[list[float]]:
            return [[1.0]]

    service = SentenceTransformerEmbeddingService(batch_size=2, model=BadModel())
    with pytest.raises(EmbeddingGenerationError, match="invalid shape"):
        service.embed_texts(["test"])


def test_document_embeddings_persist_once_and_retries_skip_existing_vectors(
    session_factory: sessionmaker[Session],
) -> None:
    """Ingestion embedding persistence is idempotent for the approved model revision."""
    service = FakeEmbeddingService()
    with session_factory() as session, session.begin():
        _project_id, document_id, chunks = _make_completed_document(session)
        assert generate_document_embeddings(
            session, document_id, embedding_service=service
        ) == 2
        assert generate_document_embeddings(
            session, document_id, embedding_service=service
        ) == 0

        rows = session.scalars(
            select(EvidenceChunkRow).where(EvidenceChunkRow.document_id == document_id)
        ).all()
        assert len(rows) == 2
        assert {row.source_chunk_id for row in rows} == {chunk.chunk_id for chunk in chunks}
        assert all(row.embedding is not None for row in rows)
        assert all(row.embedding_model_id == EMBEDDING_MODEL_ID for row in rows)
        assert all(row.embedding_model_revision == EMBEDDING_MODEL_REVISION for row in rows)

    assert len(service.batches) == 1


def test_backfill_is_batched_and_safe_to_rerun(
    session_factory: sessionmaker[Session],
) -> None:
    """Backfill repairs missing vectors in configured batches without duplicate writes."""
    service = FakeEmbeddingService()
    settings = Settings(_env_file=None, embedding_batch_size=1)
    with session_factory() as session, session.begin():
        _make_completed_document(session)

    assert backfill_missing_embeddings(
        session_factory, embedding_service=service, settings=settings
    ) == 2
    assert backfill_missing_embeddings(
        session_factory, embedding_service=service, settings=settings
    ) == 0
    assert len(service.batches) == 2
    assert all(len(batch) == 1 for batch in service.batches)


def test_repository_rejects_wrong_dimension_or_non_finite_vectors(
    session_factory: sessionmaker[Session],
) -> None:
    """Invalid embeddings cannot be stored under the 384-dimensional model contract."""
    with session_factory() as session, session.begin():
        _project_id, document_id, chunks = _make_completed_document(session)
        repository = PersistenceRepository(session)
        with pytest.raises(PersistenceContractError, match="384 finite"):
            repository.store_evidence_embeddings(
                document_id=document_id,
                embeddings={chunks[0].chunk_id: [0.0, float("nan")]},
                model_id=EMBEDDING_MODEL_ID,
                model_revision=EMBEDDING_MODEL_REVISION,
            )
