"""Tests for retrieval-backed numeric verification and result persistence."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from domain.entities import NLIClassification, NLILabel, VerdictStatus
from domain.schemas import (
    AnchorKind,
    CheckResult,
    Claim,
    ClaimType,
    EvidenceChunk,
    IngestionResult,
    NumericSlots,
    SourceAnchor,
)
from eg_common.ids import derive_uuid
from eg_common.settings import Settings
from evaluation.export_policy_inputs import export_dev_inputs
from persistence.models import (
    Base,
    DocumentRow,
    NLIResultRow,
    NumericCheckRow,
    RerankerResultRow,
    VerdictEvidenceRow,
    VerdictRow,
    VerificationEvidenceRow,
    VerificationResultRow,
)
from persistence.repositories import PersistenceRepository
from worker.orchestration import ingestion, semantic_verification, verification


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated persistence store for verification pipeline tests."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _anchor(document_id: UUID, anchor_id: str) -> SourceAnchor:
    """Build a source location with stable test provenance."""
    return SourceAnchor(
        anchor_id=anchor_id,
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=80,
        extraction_method="test-parser",
        parser_version="test-v1",
    )


def _chunk(document_id: UUID, anchor_id: str, text: str) -> EvidenceChunk:
    """Build a chunk retaining the supplied source anchor."""
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=_anchor(document_id, anchor_id),
        text=text,
    )


def _claim(document_id: UUID) -> Claim:
    """Build a quantitative claim with exact decimal semantics."""
    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="Our model achieves 91.2% accuracy on the test set.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id="claim-source",
        char_start=0,
        char_end=55,
        numeric_slots=[
            NumericSlots(
                value=Decimal("91.2"),
                metric="accuracy",
                entity="ours",
                unit="percent",
                period="test",
                decimals=1,
                source_anchor_id="claim-source",
            )
        ],
        extraction_method="test-extractor",
        extraction_confidence=0.9,
    )


def _seed(
    session: Session,
    *,
    evidence: list[EvidenceChunk],
) -> tuple[UUID, UUID, Claim]:
    """Persist completed source and evidence documents plus one claim."""
    project_id, document_id = uuid4(), uuid4()
    repository = PersistenceRepository(session)
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="claim.pdf",
        file_hash="a" * 64,
        storage_path="claim.pdf",
        file_type="pdf",
    )
    claim_source = _chunk(document_id, "claim-source", "Claim source paragraph.")
    repository.store_ingestion_result(document_id, IngestionResult(chunks=[claim_source]))
    source_claim = _claim(document_id)
    repository.store_claims([source_claim])
    source_document = session.get(DocumentRow, document_id)
    assert source_document is not None
    source_document.status = "complete"

    for index, chunk in enumerate(evidence):
        repository.create_document(
            document_id=chunk.document_id,
            project_id=project_id,
            filename=f"evidence-{index}.pdf",
            file_hash=f"{index + 1:064x}",
            storage_path=f"evidence-{index}.pdf",
            file_type="pdf",
        )
        repository.store_ingestion_result(
            chunk.document_id, IngestionResult(chunks=[chunk])
        )
        document = session.get(DocumentRow, chunk.document_id)
        assert document is not None
        document.status = "complete"
    return project_id, document_id, source_claim


def _evidence(
    document_id: UUID,
    value: str,
    period: str = "test",
    chunk_id: UUID | None = None,
) -> EvidenceChunk:
    """Create structured evidence understood by B's numeric slot parser."""
    return EvidenceChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id,
        anchor=SourceAnchor(
            anchor_id=f"evidence-{document_id}",
            document_id=document_id,
            kind=AnchorKind.TABLE_ROW,
            extraction_method="test-parser",
            parser_version="test-v1",
        ),
        text=f"Accuracy Ours {value}",
        caption=f"Results on the {period} set",
        cells={"Model": "Ours", "Accuracy (%)": value},
    )


@pytest.mark.parametrize(
    ("value", "period", "expected"),
    [
        ("91.2", "test", CheckResult.MATCH),
        ("85.4", "test", CheckResult.MISMATCH),
        ("91.2", "training", CheckResult.INCOMPARABLE),
    ],
)
def test_retrieved_numeric_evidence_is_verified_and_persisted_with_decimal_checks(
    session_factory: sessionmaker[Session], value: str, period: str, expected: CheckResult
) -> None:
    """Matching, contradictory, and incomparable retrieved evidence round-trips precisely."""
    evidence_document_id = uuid4()
    evidence = _evidence(evidence_document_id, value, period)
    with session_factory() as session, session.begin():
        _project_id, document_id, claim = _seed(session, evidence=[evidence])
        outputs = verification.verify_and_persist_document_claims(
            session,
            document_id,
            settings=Settings(_env_file=None, retrieval_top_k=10),
        )
        assert outputs[0].evidence == [evidence]
        assert outputs[0].results[0].overall == expected
        persisted_claim_id = derive_uuid(
            document_id, claim.source_anchor_id, claim.char_start, claim.char_end
        )
        assert outputs[0].claim_id == persisted_claim_id
        result_row = session.scalar(
            select(VerificationResultRow).where(
                VerificationResultRow.claim_id == persisted_claim_id,
                VerificationResultRow.result_type == "numeric_slot",
            )
        )
        assert result_row is not None
        check_row = session.scalar(
            select(NumericCheckRow).where(
                NumericCheckRow.verification_result_id == result_row.id
            )
        )
        assert check_row is not None
        assert check_row.result == expected.value
        evidence_link = session.get(
            VerificationEvidenceRow,
            (result_row.id, check_row.evidence_chunk_id),
        )
        assert evidence_link is not None
        if expected is CheckResult.INCOMPARABLE:
            assert check_row.difference is None
            assert check_row.tolerance is None
        else:
            assert isinstance(check_row.difference, Decimal)
            if expected is CheckResult.MISMATCH:
                assert check_row.difference == Decimal("0.058")
            else:
                assert check_row.difference == Decimal("0.0")


def test_own_source_is_excluded_and_missing_evidence_stays_incomparable(
    session_factory: sessionmaker[Session],
) -> None:
    """Retrieval excludes the claim anchor and an empty result invents no numeric checks."""
    with session_factory() as session, session.begin():
        _project_id, document_id, _claim_obj = _seed(session, evidence=[])
        outputs = verification.verify_and_persist_document_claims(
            session,
            document_id,
            settings=Settings(_env_file=None, retrieval_top_k=10),
        )
        assert outputs[0].evidence == []
        assert outputs[0].results[0].overall is CheckResult.INCOMPARABLE
        assert outputs[0].results[0].reason == "no_numeric_evidence"
        assert outputs[0].results[0].per_evidence == []
        assert session.scalar(select(NumericCheckRow.id)) is None


def test_verification_retries_reuse_run_and_do_not_duplicate_results(
    session_factory: sessionmaker[Session],
) -> None:
    """Repeating a document verification produces the same result rows and exact values."""
    evidence = _evidence(uuid4(), "91.2")
    with session_factory() as session, session.begin():
        _project_id, document_id, _claim_obj = _seed(session, evidence=[evidence])
        config = Settings(_env_file=None, retrieval_top_k=10)
        first = verification.verify_and_persist_document_claims(
            session, document_id, settings=config
        )
        second = verification.verify_and_persist_document_claims(
            session, document_id, settings=config
        )
        assert second == first
        result_rows = session.scalars(select(VerificationResultRow)).all()
        check_rows = session.scalars(select(NumericCheckRow)).all()
        assert len(result_rows) == 1
        assert len(check_rows) == 1
        assert check_rows[0].difference == Decimal("0.0")


def test_same_extractor_chunk_id_keeps_document_scoped_evidence_provenance(
    session_factory: sessionmaker[Session],
) -> None:
    """Checks link to the right persisted document when B's source IDs repeat."""
    shared_source_chunk_id = uuid4()
    first = _evidence(uuid4(), "91.2", chunk_id=shared_source_chunk_id)
    second = _evidence(uuid4(), "85.4", chunk_id=shared_source_chunk_id)
    with session_factory() as session, session.begin():
        _project_id, document_id, claim = _seed(session, evidence=[first, second])
        outputs = verification.verify_and_persist_document_claims(
            session,
            document_id,
            settings=Settings(_env_file=None, retrieval_top_k=10),
        )
        assert outputs[0].results[0].overall is CheckResult.INCOMPARABLE
        persisted_claim_id = derive_uuid(
            document_id, claim.source_anchor_id, claim.char_start, claim.char_end
        )
        result_row = session.scalar(
            select(VerificationResultRow).where(
                VerificationResultRow.claim_id == persisted_claim_id,
                VerificationResultRow.result_type == "numeric_slot",
            )
        )
        assert result_row is not None
        checks = session.scalars(
            select(NumericCheckRow)
            .where(NumericCheckRow.verification_result_id == result_row.id)
            .order_by(NumericCheckRow.check_index)
        ).all()
        assert len(checks) == 2
        assert {check.evidence_chunk_id for check in checks} == {
            derive_uuid(first.document_id, "evidence_chunk", shared_source_chunk_id),
            derive_uuid(second.document_id, "evidence_chunk", shared_source_chunk_id),
        }


def test_nli_verdict_persists_scores_provenance_and_reuses_results_on_retry(
    session_factory: sessionmaker[Session],
) -> None:
    """Semantic outputs link to retrieved chunks and retries avoid repeating inference."""
    evidence = _evidence(uuid4(), "91.2")

    class FakeNLIService:
        calls = 0

        def classify_pairs(
            self, pairs: list[tuple[str, str]]
        ) -> list[NLIClassification]:
            self.calls += 1
            return [
                NLIClassification(NLILabel.ENTAILMENT, 0.03, 0.94, 0.03)
                for _ in pairs
            ]

    class FakeReranker:
        calls = 0

        def score_pairs(self, _claim: Claim, evidence_chunks: list[EvidenceChunk]) -> list[float]:
            self.calls += 1
            return [0.9 for _ in evidence_chunks]

    nli_service = FakeNLIService()
    reranker = FakeReranker()
    settings = Settings(
        _env_file=None,
        policy_tau_ext=0.5,
        policy_tau_ret=0.5,
        policy_tau_e=0.8,
        policy_tau_c=0.8,
    )
    with session_factory() as session, session.begin():
        _project_id, document_id, claim = _seed(session, evidence=[evidence])
        numeric = verification.verify_and_persist_document_claims(
            session,
            document_id,
            settings=settings,
        )
        first = semantic_verification.generate_document_verdicts(
            session,
            document_id,
            numeric_outputs=numeric,
            settings=settings,
            nli_service=nli_service,
            reranker=reranker,
        )
        second = semantic_verification.generate_document_verdicts(
            session,
            document_id,
            numeric_outputs=numeric,
            settings=settings,
            nli_service=nli_service,
            reranker=reranker,
        )

        persisted_claim_id = derive_uuid(
            document_id, claim.source_anchor_id, claim.char_start, claim.char_end
        )
        assert first == second
        assert first[0].claim_id == persisted_claim_id
        assert first[0].verdict.status is VerdictStatus.SUPPORTED
        assert nli_service.calls == 1
        assert reranker.calls == 1
        nli_rows = session.scalars(
            select(NLIResultRow).where(NLIResultRow.claim_id == persisted_claim_id)
        ).all()
        assert len(nli_rows) == 1
        assert nli_rows[0].model_revision == semantic_verification.NLI_MODEL_REVISION
        assert nli_rows[0].entailment_score == pytest.approx(0.94)
        reranker_rows = session.scalars(
            select(RerankerResultRow).where(
                RerankerResultRow.claim_id == persisted_claim_id
            )
        ).all()
        assert len(reranker_rows) == 1
        assert reranker_rows[0].score == pytest.approx(0.9)
        assert reranker_rows[0].model_revision == semantic_verification.RERANKER_MODEL_REVISION
        verdict_rows = session.scalars(
            select(VerdictRow).where(VerdictRow.claim_id == persisted_claim_id)
        ).all()
        assert len(verdict_rows) == 1
        assert verdict_rows[0].status == "Supported"
        assert verdict_rows[0].confidence == pytest.approx(0.94)
        run_id = verdict_rows[0].run_id
        source_document = session.get(DocumentRow, document_id)
        assert source_document is not None
        source_document.status = "complete"
        (snapshot,) = export_dev_inputs(session, run_id)
        assert snapshot["claim_id"] == str(persisted_claim_id)
        assert snapshot["analysis_run_id"] == str(run_id)
        assert snapshot["pdf_sha256"] == source_document.file_hash
        assert snapshot["best_reranker_score"] == pytest.approx(0.9)
        assert snapshot["nli_results"][0]["entailment_score"] == pytest.approx(0.94)
        assert snapshot["retrieval"][0]["rank"] == 1
        assert session.scalar(
            select(VerdictEvidenceRow.verdict_id).where(
                VerdictEvidenceRow.verdict_id == verdict_rows[0].id
            )
        ) == verdict_rows[0].id


def test_unset_calibration_thresholds_persist_needs_review_without_weights(
    session_factory: sessionmaker[Session],
) -> None:
    """Default policy settings abstain while mocked NLI scores remain traceable."""
    evidence = _evidence(uuid4(), "91.2")

    class FakeNLIService:
        def classify_pairs(
            self, pairs: list[tuple[str, str]]
        ) -> list[NLIClassification]:
            return [
                NLIClassification(NLILabel.ENTAILMENT, 0.01, 0.98, 0.01)
                for _ in pairs
            ]

    class FakeReranker:
        def score_pairs(self, _claim: Claim, evidence_chunks: list[EvidenceChunk]) -> list[float]:
            return [0.9 for _ in evidence_chunks]

    with session_factory() as session, session.begin():
        _project_id, document_id, _claim_obj = _seed(session, evidence=[evidence])
        numeric = verification.verify_and_persist_document_claims(session, document_id)
        output = semantic_verification.generate_document_verdicts(
            session,
            document_id,
            numeric_outputs=numeric,
            settings=Settings(_env_file=None),
            nli_service=FakeNLIService(),
            reranker=FakeReranker(),
        )
        row = session.scalar(select(VerdictRow).where(VerdictRow.claim_id == output[0].claim_id))
        assert row is not None
        assert row.status == "Needs Review"
        assert row.reason == "threshold_unavailable:tau_ext"


def test_verdict_evidence_is_ordered_by_reranker_and_keeps_retrieval_scores(
    session_factory: sessionmaker[Session],
) -> None:
    """Reranking controls displayed evidence order without replacing retrieval provenance."""
    preferred = _evidence(uuid4(), "91.2").model_copy(
        update={"text": "Accuracy Ours 91.2 direct measurement"}
    )
    secondary = _evidence(uuid4(), "91.2").model_copy(
        update={"text": "Accuracy Ours 91.2 contextual passage"}
    )

    class FakeNLIService:
        def classify_pairs(
            self, pairs: list[tuple[str, str]]
        ) -> list[NLIClassification]:
            return [
                NLIClassification(NLILabel.ENTAILMENT, 0.02, 0.96, 0.02)
                for _ in pairs
            ]

    class FakeReranker:
        def score_pairs(
            self, _claim: Claim, chunks: list[EvidenceChunk]
        ) -> list[float]:
            return [0.95 if "direct measurement" in chunk.text else 0.2 for chunk in chunks]

    settings = Settings(
        _env_file=None,
        retrieval_top_k=10,
        policy_tau_ext=0.5,
        policy_tau_ret=0.5,
        policy_tau_e=0.8,
        policy_tau_c=0.8,
    )
    with session_factory() as session, session.begin():
        _project_id, document_id, _claim_obj = _seed(
            session, evidence=[secondary, preferred]
        )
        numeric = verification.verify_and_persist_document_claims(
            session, document_id, settings=settings
        )
        output = semantic_verification.generate_document_verdicts(
            session,
            document_id,
            numeric_outputs=numeric,
            settings=settings,
            nli_service=FakeNLIService(),
            reranker=FakeReranker(),
        )
        (verdict_row,) = session.scalars(select(VerdictRow)).all()
        retrieval = verdict_row.policy_inputs["retrieval"]
        nli_outputs = verdict_row.policy_inputs["nli_results"]
        policy_nli_ids = verdict_row.policy_inputs["policy_nli_evidence_ids"]

    assert output[0].evidence[0].text.endswith("direct measurement")
    assert retrieval[0]["rank"] == 1
    assert retrieval[0]["reranker_score"] == pytest.approx(0.95)
    assert retrieval[0]["retrieval_rank"] >= 1
    assert "retrieval_score" in retrieval[0]
    assert {item["evidence_id"] for item in nli_outputs} == {
        item["evidence_id"] for item in retrieval
    }
    assert policy_nli_ids == [retrieval[0]["evidence_id"]]


def test_worker_records_numeric_verification_failure_safely(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier errors are converted to a safe worker processing code."""
    project_id, document_id = uuid4(), uuid4()
    source_chunk = _chunk(
        document_id,
        "claim-source",
        "Our model achieves 91.2% accuracy on the test set.",
    )
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        repository.create_project(project_id)
        repository.create_document(
            document_id=document_id,
            project_id=project_id,
            filename="queued.pdf",
            file_hash="b" * 64,
            storage_path=str(tmp_path / "queued.pdf"),
            file_type="pdf",
        )

    def parse_pdf(_path: Path, _document_id: UUID, _file_hash: str) -> list[EvidenceChunk]:
        return [source_chunk]

    def fail_verify(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("private evidence text")

    class FakeEmbeddingService:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] + [0.0] * 383 for _ in texts]

    monkeypatch.setattr(ingestion, "ingest_pdf", parse_pdf)
    monkeypatch.setattr(ingestion, "verify_and_persist_document_claims", fail_verify)
    with pytest.raises(RuntimeError, match="private evidence text"):
        ingestion.process_next_document(
            session_factory,
            embedding_service=FakeEmbeddingService(),
        )
    with session_factory() as session:
        document = session.get(DocumentRow, document_id)
        assert document is not None
        assert document.status == "error"
        assert document.processing_error == "numeric_verification_failed"
