"""End-to-end queued-document processing with model inference replaced by fakes."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from domain.entities import NLIClassification, NLILabel, VerdictStatus
from domain.schemas import AnchorKind, Claim, EvidenceChunk, IngestionResult, SourceAnchor
from eg_common.ids import derive_uuid
from eg_common.settings import Settings
from persistence.models import (
    AnalysisRunRow,
    Base,
    ClaimRow,
    DocumentRow,
    EvidenceChunkRow,
    NLIResultRow,
    NumericCheckRow,
    RerankerResultRow,
    VerdictEvidenceRow,
    VerdictRow,
)
from persistence.repositories import PersistenceRepository
from worker.orchestration import ingestion, retrieval, semantic_verification, verification
from worker.orchestration.retrieval import RankedEvidence
from worker.orchestration.run_identity import analysis_run_id


class FixedEmbeddings:
    """Return fixed vectors without constructing a model or downloading weights."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one deterministic 384-dimensional vector per input."""
        return [[1.0] + [0.0] * 383 for _ in texts]


class FlakyNLI:
    """Fail once, then return deterministic entailment distributions."""

    def __init__(self) -> None:
        self.calls = 0

    def classify_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[NLIClassification]:
        """Simulate a transient local inference failure before succeeding."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("inference unavailable")
        return [NLIClassification(NLILabel.ENTAILMENT, 0.02, 0.96, 0.02) for _ in pairs]


class FixedReranker:
    """Return a stable relevance score for each claim-evidence pair."""

    def score_pairs(
        self, _claim: Claim, evidence: Sequence[EvidenceChunk]
    ) -> list[float]:
        """Keep output cardinality aligned with the retrieved evidence."""
        return [0.93 for _ in evidence]


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Create an isolated SQLAlchemy database for the complete worker path."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _chunk(document_id: UUID, *, anchor_id: str, text: str) -> EvidenceChunk:
    """Build a deterministic paragraph chunk with document provenance."""
    anchor = SourceAnchor(
        anchor_id=anchor_id,
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=len(text),
        extraction_method="integration-test",
        parser_version="integration-test-v1",
    )
    return EvidenceChunk(
        chunk_id=UUID(int=document_id.int + 100),
        document_id=document_id,
        anchor=anchor,
        text=text,
    )


def test_queued_pdf_reaches_persisted_abstaining_verdict_and_retries_idempotently(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A retry completes each stage once and preserves all linked provenance."""
    config = Settings()
    monkeypatch.setattr(verification, "get_settings", lambda: config)
    monkeypatch.setattr(semantic_verification, "get_settings", lambda: config)

    project_id = UUID(int=1)
    source_document_id = UUID(int=2)
    target_document_id = UUID(int=3)
    source_chunk = _chunk(
        source_document_id,
        anchor_id="source:p1:para0",
        text="Model A achieved 95% accuracy on the test set.",
    )
    target_chunk = _chunk(
        target_document_id,
        anchor_id="claim:p1:para0",
        text="Model A achieves 95% accuracy.",
    )
    pdf_path = tmp_path / "queued.pdf"
    pdf_path.write_bytes(b"mocked parser input")

    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        repository.create_project(project_id)
        repository.create_document(
            document_id=source_document_id,
            project_id=project_id,
            filename="source.pdf",
            file_hash="a" * 64,
            storage_path="source.pdf",
            file_type="pdf",
        )
        repository.store_ingestion_result(
            source_document_id,
            IngestionResult(chunks=[source_chunk]),
        )
        source = session.get(DocumentRow, source_document_id)
        assert source is not None
        source.status = "complete"
        repository.create_document(
            document_id=target_document_id,
            project_id=project_id,
            filename="queued.pdf",
            file_hash="b" * 64,
            storage_path=str(pdf_path),
            file_type="pdf",
        )

    monkeypatch.setattr(
        ingestion,
        "ingest_pdf",
        lambda _path, _document_id, _file_hash: [target_chunk],
    )
    dense_calls: list[str] = []

    def dense_candidates(*_args: object, **_kwargs: object) -> list[RankedEvidence]:
        """Represent deterministic pgvector results while SQLite backs this test."""
        dense_calls.append("called")
        return [RankedEvidence(chunk=source_chunk, score=0.88, rank=1)]

    monkeypatch.setattr(retrieval, "dense_retrieve_project_evidence", dense_candidates)
    nli_service = FlakyNLI()
    embedder = FixedEmbeddings()
    reranker = FixedReranker()

    with pytest.raises(RuntimeError, match="inference unavailable"):
        ingestion.process_next_document(
            session_factory,
            embedding_service=embedder,
            nli_service=nli_service,
            reranker=reranker,
        )

    with session_factory() as session:
        failed = session.get(DocumentRow, target_document_id)
        assert failed is not None
        assert failed.status == "error"
        assert failed.processing_error == "semantic_verification_failed"
        assert session.scalar(
            select(ClaimRow.id).where(ClaimRow.document_id == target_document_id)
        ) is None

    with session_factory() as session, session.begin():
        queued = session.get(DocumentRow, target_document_id)
        assert queued is not None
        queued.status = "queued"
        queued.processing_error = None

    assert ingestion.process_next_document(
        session_factory,
        embedding_service=embedder,
        nli_service=nli_service,
        reranker=reranker,
    )

    run_id = analysis_run_id(target_document_id, config)
    with session_factory() as session:
        repository = PersistenceRepository(session)
        document = session.get(DocumentRow, target_document_id)
        assert document is not None and document.status == "complete"
        claim_rows = list(
            session.scalars(
                select(ClaimRow).where(ClaimRow.document_id == target_document_id)
            )
        )
        assert len(claim_rows) == 1
        claim_id = claim_rows[0].id
        assert session.get(AnalysisRunRow, run_id) is not None
        assert len(list(session.scalars(select(EvidenceChunkRow)))) == 2
        assert len(list(session.scalars(select(NumericCheckRow.id)))) == 1
        assert len(list(session.scalars(select(NLIResultRow.id)))) == 1
        assert len(list(session.scalars(select(RerankerResultRow.id)))) == 1

        verdicts = repository.list_verdicts(run_id, claim_id)
        assert len(verdicts) == 1
        persisted = verdicts[0]
        assert persisted.verdict.status is VerdictStatus.NEEDS_REVIEW
        assert persisted.verdict.reason == "threshold_unavailable:tau_ext"
        assert persisted.verdict.explanation
        assert persisted.verdict.confidence is None
        assert persisted.policy_version
        assert len(persisted.evidence_chunk_ids) == 1
        assert persisted.evidence_chunk_ids == (
            derive_uuid(source_document_id, "evidence_chunk", source_chunk.chunk_id),
        )
        assert session.scalar(select(VerdictRow.id)) is not None
        assert session.scalar(select(VerdictEvidenceRow.verdict_id)) is not None
        nli_results = repository.list_nli_results(run_id, claim_id)
        assert nli_results[0].classification.entailment_score == 0.96
        reranker_results = repository.list_reranker_results(run_id, claim_id)
        assert reranker_results == [(persisted.evidence_chunk_ids[0], 0.93)]
        numeric_results = repository.list_numeric_verifications(run_id, claim_id)
        assert numeric_results
        assert numeric_results[0].per_evidence
        assert len(repository.list_verdicts(run_id)) == 1

        retrieved = repository.get_ingestion_result(source_document_id).chunks[0]
        assert retrieved.chunk_id == source_chunk.chunk_id
        assert retrieved.anchor.anchor_id == source_chunk.anchor.anchor_id
        assert retrieved.document_id == source_document_id

    assert nli_service.calls == 2
    assert len(dense_calls) == 2
