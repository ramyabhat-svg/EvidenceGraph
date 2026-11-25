"""Unit tests for BM25 ranking, reciprocal-rank fusion, and persisted retrieval."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import (
    AnchorKind,
    Claim,
    ClaimType,
    EvidenceChunk,
    IngestionResult,
    SourceAnchor,
)
from eg_common.settings import Settings
from persistence.models import Base, DocumentRow
from persistence.repositories import PersistenceRepository
from worker.orchestration.retrieval import (
    RankedEvidence,
    RetrievalContractError,
    bm25_retrieve,
    reciprocal_rank_fusion,
    retrieve_for_claim,
    retrieve_project_evidence,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated SQLite database for retrieval integration tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _chunk(document_id: UUID, chunk_number: int, text: str) -> EvidenceChunk:
    """Build an evidence chunk with a unique, traceable source anchor."""
    anchor = SourceAnchor(
        anchor_id=f"document:p1:para{chunk_number}",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=chunk_number * 100,
        char_end=chunk_number * 100 + len(text),
        extraction_method="test-parser",
        parser_version="test-v1",
    )
    return EvidenceChunk(
        chunk_id=uuid4(), document_id=document_id, anchor=anchor, text=text
    )


def test_bm25_ranks_relevant_chunks_and_respects_top_k() -> None:
    """BM25 prefers matching terms and returns only the configured number of results."""
    document_id = uuid4()
    chunks = [
        _chunk(document_id, 0, "Neural network accuracy improved substantially."),
        _chunk(document_id, 1, "The network uses a neural architecture."),
        _chunk(document_id, 2, "A separate experiment measured runtime."),
    ]

    results = bm25_retrieve("neural accuracy", chunks, top_k=1, k1=1.5, b=0.75)

    assert len(results) == 1
    assert results[0].chunk == chunks[0]
    assert results[0].rank == 1
    assert results[0].score > 0


def test_bm25_empty_or_unmatched_queries_return_no_candidates() -> None:
    """Empty and out-of-vocabulary queries do not produce zero-score evidence."""
    chunk = _chunk(uuid4(), 0, "A measured result.")

    assert bm25_retrieve("   ", [chunk], top_k=4, k1=1.5, b=0.75) == []
    assert bm25_retrieve("unmatched", [chunk], top_k=4, k1=1.5, b=0.75) == []


def test_rrf_combines_rankings_and_deduplicates_source_chunks() -> None:
    """RRF adds contributions from independent rankings and preserves chunk provenance."""
    first = _chunk(uuid4(), 0, "first evidence")
    second = _chunk(uuid4(), 1, "second evidence")
    sparse = [
        RankedEvidence(first, score=2.0, rank=1),
        RankedEvidence(second, score=1.0, rank=2),
    ]
    dense = [RankedEvidence(second, score=0.9, rank=3), RankedEvidence(first, 0.8, 2)]

    results = reciprocal_rank_fusion([sparse, dense], rrf_k=10, top_k=2)

    assert [item.chunk for item in results] == [first, second]
    assert results[0].score == pytest.approx(1 / 11 + 1 / 12)
    assert results[0].rrf_score == pytest.approx(results[0].score)
    assert results[1].score == pytest.approx(1 / 12 + 1 / 13)
    assert [item.rank for item in results] == [1, 2]


def test_rrf_preserves_component_scores_and_ranks() -> None:
    """Fused output retains the independent BM25 and dense diagnostics."""
    chunk = _chunk(uuid4(), 0, "combined evidence")
    result = reciprocal_rank_fusion(
        [[RankedEvidence(chunk, 2.4, 2, bm25_score=2.4, bm25_rank=2)],
         [RankedEvidence(chunk, 0.82, 1, dense_score=0.82, dense_rank=1)]],
        rrf_k=10,
        top_k=1,
    )[0]
    assert result.bm25_score == 2.4
    assert result.bm25_rank == 2
    assert result.dense_score == 0.82
    assert result.dense_rank == 1


def test_rrf_rejects_conflicting_duplicate_identity() -> None:
    """The same document-scoped chunk ID cannot hide conflicting provenance."""
    original = _chunk(uuid4(), 0, "first evidence")
    conflicting = original.model_copy(update={"text": "different text"})

    with pytest.raises(RetrievalContractError, match="conflicting"):
        reciprocal_rank_fusion(
            [[RankedEvidence(original, 1.0, 1)], [RankedEvidence(conflicting, 1.0, 1)]],
            rrf_k=10,
            top_k=2,
        )


def test_project_retrieval_reads_persisted_chunks_and_excludes_source_anchor(
    session_factory: sessionmaker[Session],
) -> None:
    """The verification-facing interface searches stored chunks with provenance intact."""
    project_id, source_document_id, evidence_document_id, queued_document_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    source_chunk = _chunk(source_document_id, 0, "The model has neural accuracy results.")
    evidence_chunk = _chunk(evidence_document_id, 0, "Neural accuracy reached a strong value.")
    queued_chunk = _chunk(queued_document_id, 0, "Neural accuracy from an incomplete upload.")
    settings = Settings(_env_file=None, retrieval_top_k=10)

    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        repository.create_project(project_id)
        for document_id, file_hash in (
            (source_document_id, "a" * 64),
            (evidence_document_id, "b" * 64),
            (queued_document_id, "c" * 64),
        ):
            repository.create_document(
                document_id=document_id,
                project_id=project_id,
                filename=f"{file_hash[:1]}.pdf",
                file_hash=file_hash,
                storage_path=f"{file_hash[:1]}.pdf",
                file_type="pdf",
            )
        repository.store_ingestion_result(
            source_document_id, IngestionResult(chunks=[source_chunk])
        )
        repository.store_ingestion_result(
            evidence_document_id, IngestionResult(chunks=[evidence_chunk])
        )
        repository.store_ingestion_result(
            queued_document_id, IngestionResult(chunks=[queued_chunk])
        )
        for document_id in (source_document_id, evidence_document_id):
            document = session.get(DocumentRow, document_id)
            assert document is not None
            document.status = "complete"

        claim = Claim(
            claim_id=uuid4(),
            document_id=source_document_id,
            claim_text="Neural accuracy was measured.",
            claim_type=ClaimType.QUANTITATIVE,
            source_anchor_id=source_chunk.anchor.anchor_id,
            char_start=0,
            char_end=30,
            extraction_method="test-extractor",
            extraction_confidence=0.8,
        )
        results = retrieve_for_claim(
            session, project_id, claim,
            settings=settings,
        )

    assert [item.chunk.chunk_id for item in results] == [evidence_chunk.chunk_id]
    assert results[0].chunk.document_id == evidence_document_id
    assert results[0].chunk.anchor == evidence_chunk.anchor


def test_project_retrieval_requires_existing_project(
    session_factory: sessionmaker[Session],
) -> None:
    """Unknown project IDs fail with the persistence not-found contract."""
    with session_factory() as session:
        with pytest.raises(LookupError, match="project"):
            retrieve_project_evidence(session, uuid4(), "query")
