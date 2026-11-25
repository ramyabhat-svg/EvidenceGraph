"""Database integration coverage for retrieval over persisted evidence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import AnchorKind, EvidenceChunk, IngestionResult, SourceAnchor
from eg_common.settings import Settings
from persistence.models import DocumentRow
from persistence.repositories import PersistenceRepository
from worker.orchestration.embeddings import EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION
from worker.orchestration.retrieval import retrieve_project_evidence


@pytest.fixture
def integration_session() -> Iterator[Session]:
    """Open an isolated transaction on TEST_DATABASE_URL for retrieval integration."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("TEST_DATABASE_URL is required for CI integration tests")
        pytest.skip("TEST_DATABASE_URL is not configured")

    engine = create_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_bm25_retrieves_persisted_evidence_with_source_provenance(
    integration_session: Session,
) -> None:
    """The retrieval interface returns source chunk identity and anchor from the DB."""
    session = integration_session
    project_id = uuid4()
    document_id = uuid4()
    anchor = SourceAnchor(
        anchor_id="integration:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=36,
        extraction_method="integration-test",
        parser_version="integration-v1",
    )
    chunk = EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text="Neural accuracy improved in the experiment.",
    )

    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="report.pdf",
        file_hash=uuid4().hex,
        storage_path="integration/report.pdf",
        file_type="pdf",
    )
    repository.store_ingestion_result(document_id, IngestionResult(chunks=[chunk]))
    document = session.get(DocumentRow, document_id)
    assert document is not None
    document.status = "complete"

    results = retrieve_project_evidence(
        session,
        project_id,
        "neural accuracy",
        settings=Settings(_env_file=None, retrieval_top_k=5),
    )

    assert len(results) == 1
    assert results[0].chunk.chunk_id == chunk.chunk_id
    assert results[0].chunk.document_id == document_id
    assert results[0].chunk.anchor == anchor


def test_dense_retrieval_uses_cosine_distance_and_preserves_provenance(
    integration_session: Session,
) -> None:
    """PostgreSQL dense top-k searches stored vectors and returns original source metadata."""
    session = integration_session
    project_id, document_id = uuid4(), uuid4()
    texts = ["evidence with unrelated words", "another separate passage"]
    chunks = []
    for index, text in enumerate(texts):
        anchor = SourceAnchor(
            anchor_id=f"dense:p1:para{index}",
            document_id=document_id,
            kind=AnchorKind.PARAGRAPH,
            page=1,
            char_start=index * 50,
            char_end=index * 50 + len(text),
            extraction_method="dense-integration-test",
            parser_version="dense-v1",
        )
        chunks.append(
            EvidenceChunk(
                chunk_id=uuid4(),
                document_id=document_id,
                anchor=anchor,
                text=text,
            )
        )

    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="dense.pdf",
        file_hash=uuid4().hex,
        storage_path="integration/dense.pdf",
        file_type="pdf",
    )
    repository.store_ingestion_result(document_id, IngestionResult(chunks=chunks))
    document = session.get(DocumentRow, document_id)
    assert document is not None
    document.status = "complete"
    first_vector = [1.0] + [0.0] * 383
    second_vector = [0.0, 1.0] + [0.0] * 382
    repository.store_evidence_embeddings(
        document_id=document_id,
        embeddings={
            chunks[0].chunk_id: first_vector,
            chunks[1].chunk_id: second_vector,
        },
        model_id=EMBEDDING_MODEL_ID,
        model_revision=EMBEDDING_MODEL_REVISION,
    )

    class QueryEmbeddingService:
        """Return a query vector aligned with the first persisted vector."""

        def embed_texts(self, query_texts: list[str]) -> list[list[float]]:
            assert query_texts == ["semantic needle"]
            return [first_vector]

    results = retrieve_project_evidence(
        session,
        project_id,
        "semantic needle",
        settings=Settings(_env_file=None, retrieval_top_k=1),
        embedding_service=QueryEmbeddingService(),
    )

    assert len(results) == 1
    assert results[0].chunk.chunk_id == chunks[0].chunk_id
    assert results[0].chunk.anchor == chunks[0].anchor


def test_missing_dense_vectors_fall_back_without_loading_an_embedder(
    integration_session: Session,
) -> None:
    """BM25 remains available when the document has not been embedded yet."""
    session = integration_session
    project_id, document_id = uuid4(), uuid4()
    anchor = SourceAnchor(
        anchor_id="missing-vector:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=24,
        extraction_method="missing-vector-test",
        parser_version="missing-v1",
    )
    chunk = EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text="Neural accuracy measured.",
    )
    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="missing.pdf",
        file_hash=uuid4().hex,
        storage_path="integration/missing.pdf",
        file_type="pdf",
    )
    repository.store_ingestion_result(document_id, IngestionResult(chunks=[chunk]))
    document = session.get(DocumentRow, document_id)
    assert document is not None
    document.status = "complete"

    class UnexpectedEmbeddingService:
        """Fail if retrieval tries to load or use embeddings when no vectors exist."""

        def embed_texts(self, _texts: list[str]) -> list[list[float]]:
            raise AssertionError("embedder should not run when all vectors are missing")

    results = retrieve_project_evidence(
        session,
        project_id,
        "neural accuracy",
        embedding_service=UnexpectedEmbeddingService(),
    )

    assert [item.chunk.chunk_id for item in results] == [chunk.chunk_id]
