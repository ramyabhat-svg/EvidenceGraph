"""Tests for repository identity, round-trip, and immutability behavior."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import (
    AnchorKind,
    CheckResult,
    Claim,
    ClaimType,
    EvidenceChunk,
    IngestionResult,
    NumericCheck,
    NumericSlots,
    SourceAnchor,
)
from domain_packs.scientific_research.pack import ValidationResult
from eg_common.ids import derive_uuid
from persistence.models import Base, ClaimRow, DocumentRow, EvidenceChunkRow
from persistence.repositories import (
    PersistenceConflictError,
    PersistenceContractError,
    PersistenceRepository,
)
from worker.verification.numeric import SlotVerification


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Create an isolated in-memory database for one repository test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _make_anchor(document_id: UUID, anchor_id: str = "doc:p1:para0") -> SourceAnchor:
    return SourceAnchor(
        anchor_id=anchor_id,
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=70,
        extraction_method="test_parser",
        parser_version="parser-v1",
    )


def _make_chunk(document_id: UUID, anchor_id: str, text: str) -> EvidenceChunk:
    anchor = _make_anchor(document_id, anchor_id)
    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text=text,
    )


def _make_claim(document_id: UUID, anchor_id: str) -> Claim:
    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="The model reaches 0.123456789012345678901234567890 accuracy.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id=anchor_id,
        char_start=0,
        char_end=65,
        numeric_slots=[
            NumericSlots(
                metric="accuracy",
                value=Decimal("0.123456789012345678901234567890"),
                decimals=30,
                source_anchor_id=anchor_id,
            )
        ],
        extraction_method="rules-test",
        extraction_confidence=0.9,
    )


def _create_pdf_document(repository: PersistenceRepository) -> tuple[UUID, UUID]:
    project_id = uuid4()
    document_id = uuid4()
    repository.create_project(project_id)
    repository.create_document(
        document_id=document_id,
        project_id=project_id,
        filename="paper.pdf",
        file_hash="a" * 64,
        storage_path="storage/project/paper.pdf",
        file_type="pdf",
    )
    return project_id, document_id


def test_ingestion_result_round_trip_is_ordered_and_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    document_id = uuid4()
    first = _make_chunk(document_id, "doc:p1:para0", "First chunk")
    second = _make_chunk(document_id, "doc:p1:para1", "Second chunk")
    result = IngestionResult(chunks=[second, first])

    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        project_id = uuid4()
        repository.create_project(project_id)
        repository.create_document(
            document_id=document_id,
            project_id=project_id,
            filename="paper.pdf",
            file_hash="b" * 64,
            storage_path="storage/paper.pdf",
            file_type="pdf",
        )
        repository.store_ingestion_result(document_id, result)
        repository.store_ingestion_result(document_id, result)

    with session_factory() as session:
        restored = PersistenceRepository(session).get_ingestion_result(document_id)
    assert restored == result


def test_ingestion_error_is_persisted_without_inventing_a_claim_verdict(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        _, document_id = _create_pdf_document(PersistenceRepository(session))
        result = IngestionResult(processing_error="scanned_pdf_unsupported")
        PersistenceRepository(session).store_ingestion_result(document_id, result)

    with session_factory() as session:
        restored = PersistenceRepository(session).get_ingestion_result(document_id)
    assert restored.processing_error == "scanned_pdf_unsupported"
    assert restored.chunks == []


def test_claim_identity_and_decimal_slots_round_trip(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        _, document_id = _create_pdf_document(repository)
        chunk = _make_chunk(document_id, "claim-anchor", "Claim source text")
        repository.store_ingestion_result(document_id, IngestionResult(chunks=[chunk]))
        claim = _make_claim(document_id, chunk.anchor.anchor_id)
        assert repository.store_claims([claim]) == [claim]
        claim_id = derive_uuid(
            document_id, claim.source_anchor_id, claim.char_start, claim.char_end
        )
        assert session.get(ClaimRow, claim_id) is not None

    with session_factory() as session:
        repository = PersistenceRepository(session)
        restored = repository.get_claim(claim_id)

    assert restored == claim
    assert restored.claim_id == claim.claim_id
    assert restored.numeric_slots[0].value == Decimal("0.123456789012345678901234567890")


def test_duplicate_pdf_hash_is_project_scoped(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        project_id, first_id = _create_pdf_document(repository)
        other_project_id = uuid4()
        repository.create_project(other_project_id)
        repository.create_document(
            document_id=uuid4(),
            project_id=other_project_id,
            filename="same-hash.pdf",
            file_hash="c" * 64,
            storage_path="storage/other/same-hash.pdf",
            file_type="pdf",
        )

    with session_factory() as session:
        repository = PersistenceRepository(session)
        with pytest.raises(IntegrityError):
            with session.begin():
                repository.create_document(
                    document_id=uuid4(),
                    project_id=project_id,
                    filename="duplicate.pdf",
                    file_hash="a" * 64,
                    storage_path="storage/duplicate.pdf",
                    file_type="pdf",
                )
        assert session.get(DocumentRow, first_id) is not None


def test_companion_csv_must_reference_a_pdf_in_the_same_project(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        project_id, parent_id = _create_pdf_document(repository)
        other_project = repository.create_project().id
        with pytest.raises(PersistenceContractError):
            repository.create_document(
                document_id=uuid4(),
                project_id=other_project,
                filename="support.csv",
                file_hash="d" * 64,
                storage_path="storage/support.csv",
                file_type="csv",
                parent_document_id=uuid4(),
            )
        csv = repository.create_document(
            document_id=uuid4(),
            project_id=project_id,
            filename="support.csv",
            file_hash="e" * 64,
            storage_path="storage/support.csv",
            file_type="csv",
            parent_document_id=parent_id,
        )
        assert csv.parent_document_id is not None


def test_numeric_and_pack_results_are_run_scoped_and_separately_restored(
    session_factory: sessionmaker[Session],
) -> None:
    value = Decimal("0.123456789012345678901234567890")
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        _project_id, document_id = _create_pdf_document(repository)
        chunk = _make_chunk(document_id, "evidence-anchor", "Evidence")
        claim_chunk = _make_chunk(document_id, "claim-anchor", "Claim source")
        repository.store_ingestion_result(
            document_id,
            IngestionResult(chunks=[chunk, claim_chunk]),
        )
        claim = _make_claim(document_id, claim_chunk.anchor.anchor_id)
        repository.store_claims([claim])
        claim_id = derive_uuid(
            document_id, claim.source_anchor_id, claim.char_start, claim.char_end
        )
        run_id = uuid4()
        repository.create_analysis_run(
            run_id=run_id,
            document_id=document_id,
            configuration={"approx_multiplier": "2"},
            model_versions={"numeric": "numeric-1"},
            policy_version=None,
        )
        evidence_id = derive_uuid(document_id, "evidence_chunk", chunk.chunk_id)
        check = NumericCheck(
            result=CheckResult.MATCH,
            claim_slots=NumericSlots(value=value, decimals=30),
            evidence_slots=NumericSlots(value=value, decimals=30),
            tolerance=Decimal("0.0000000000000000000000000000005"),
            difference=Decimal("0E-30"),
            trace=["exact comparison"],
            validator_version="numeric-test-v1",
        )
        numeric_result = SlotVerification(
            slot_index=0,
            overall=CheckResult.MATCH,
            reason="matching_evidence_found",
            per_evidence=[(chunk.chunk_id, check)],
        )
        evidence_map = {chunk.chunk_id: evidence_id}
        repository.store_numeric_verifications(
            run_id=run_id,
            claim_id=claim_id,
            results=[numeric_result],
            evidence_persistence_ids=evidence_map,
        )
        pack_result = ValidationResult(
            validator="table_to_text",
            result=CheckResult.MATCH,
            trace=["pack output"],
        )
        repository.store_pack_validation_results(
            run_id=run_id,
            claim_id=claim_id,
            results=[pack_result],
            evidence_persistence_ids=[evidence_id],
        )
        second_run = uuid4()
        repository.create_analysis_run(
            run_id=second_run,
            document_id=document_id,
            configuration={"approx_multiplier": "2"},
            model_versions={"numeric": "numeric-1"},
            policy_version=None,
        )
        assert session.get(EvidenceChunkRow, evidence_id) is not None

    with session_factory() as session:
        repository = PersistenceRepository(session)
        numeric = repository.list_numeric_verifications(run_id, claim_id)
        pack = repository.list_pack_validation_results(run_id, claim_id)
        other_run = repository.list_numeric_verifications(second_run, claim_id)

    assert numeric == [numeric_result]
    assert numeric[0].per_evidence[0][1].tolerance == check.tolerance
    assert numeric[0].per_evidence[0][1].claim_slots.value == value
    assert pack == [pack_result]
    assert other_run == []


def test_immutable_claim_and_run_retries_reject_changed_payload(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        repository = PersistenceRepository(session)
        _, document_id = _create_pdf_document(repository)
        chunk = _make_chunk(document_id, "claim-anchor", "Claim source")
        repository.store_ingestion_result(document_id, IngestionResult(chunks=[chunk]))
        claim = _make_claim(document_id, chunk.anchor.anchor_id)
        repository.store_claims([claim])
        claim.claim_text = "Changed text"
        with pytest.raises(PersistenceConflictError):
            repository.store_claims([claim])

        run_id = uuid4()
        repository.create_analysis_run(
            run_id=run_id,
            document_id=document_id,
            configuration={"version": 1},
            model_versions={},
            policy_version=None,
        )
        with pytest.raises(PersistenceConflictError):
            repository.create_analysis_run(
                run_id=run_id,
                document_id=document_id,
                configuration={"version": 2},
                model_versions={},
                policy_version=None,
            )
