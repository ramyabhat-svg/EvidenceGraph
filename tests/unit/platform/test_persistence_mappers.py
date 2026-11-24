"""Round-trip coverage for explicit conversions of Member B domain objects."""

from decimal import Decimal
from uuid import uuid4

from domain.schemas import (
    AnchorKind,
    CheckResult,
    Claim,
    ClaimType,
    EvidenceChunk,
    NumericCheck,
    NumericSlots,
    SourceAnchor,
)
from domain_packs.scientific_research.pack import ValidationResult
from persistence.mappers import (
    claim_from_row,
    claim_values,
    evidence_chunk_from_row,
    evidence_chunk_values,
    numeric_check_from_row,
    numeric_check_values,
    slot_verification_from_rows,
    slot_verification_values,
    source_anchor_from_row,
    source_location_values,
    validation_result_from_row,
    validation_result_values,
)
from persistence.models import (
    ClaimRow,
    EvidenceChunkRow,
    NumericCheckRow,
    SourceLocationRow,
    VerificationResultRow,
)
from worker.verification.numeric import SlotVerification


def _anchor(document_id):
    return SourceAnchor(
        anchor_id="doc:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=10,
        char_end=45,
        bbox=(1.0, 2.0, 3.0, 4.0),
        low_quality=True,
        low_quality_reasons=["test_quality_reason"],
        extraction_method="test_parser",
        parser_version="parser-v1",
    )


def _claim(document_id, anchor_id):
    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="The model achieves 0.123456789012345678901234567890 accuracy.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id=anchor_id,
        char_start=0,
        char_end=60,
        numeric_slots=[
            NumericSlots(
                raw_text="0.123456789012345678901234567890",
                metric="accuracy",
                value=Decimal("0.123456789012345678901234567890"),
                decimals=30,
                source_anchor_id=anchor_id,
            )
        ],
        extraction_method="rules-test",
        extraction_confidence=0.8,
        low_quality=True,
    )


def test_source_anchor_and_evidence_chunk_mappers_round_trip():
    document_id = uuid4()
    anchor = _anchor(document_id)
    location_values = source_location_values(anchor)
    location_row = SourceLocationRow(**location_values)
    restored_anchor = source_anchor_from_row(location_row)

    assert restored_anchor == anchor

    chunk = EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text="A source paragraph with exact context.",
        headers=["Metric", "Value"],
        caption="Table 1",
        cells={"Metric": "accuracy", "Value": "0.9"},
    )
    chunk_values = evidence_chunk_values(chunk, location_row.id, ordinal=0)
    chunk_row = EvidenceChunkRow(**chunk_values)

    assert chunk_row.id != chunk.chunk_id
    assert chunk_row.source_chunk_id == chunk.chunk_id
    assert evidence_chunk_from_row(chunk_row, restored_anchor) == chunk


def test_claim_mapper_preserves_extractor_id_and_decimal_slots():
    document_id = uuid4()
    anchor = _anchor(document_id)
    claim = _claim(document_id, anchor.anchor_id)
    location_id = source_location_values(anchor)["id"]
    row = ClaimRow(**claim_values(claim, location_id))

    restored = claim_from_row(row)

    assert row.id != claim.claim_id
    assert row.extractor_claim_id == claim.claim_id
    assert restored == claim
    assert restored.numeric_slots[0].value == Decimal("0.123456789012345678901234567890")


def test_numeric_verification_and_check_mappers_round_trip():
    run_id = uuid4()
    claim_id = uuid4()
    source_chunk_id = uuid4()
    evidence_id = uuid4()
    precision = Decimal("0.123456789012345678901234567890")
    check = NumericCheck(
        result=CheckResult.MATCH,
        claim_slots=NumericSlots(value=precision, decimals=30),
        evidence_slots=NumericSlots(value=precision, decimals=30),
        tolerance=Decimal("0.0000000000000000000000000000005"),
        difference=Decimal("0E-30"),
        trace=["exact decimal check"],
        validator_version="numeric-test-v1",
    )
    slot_result = SlotVerification(
        slot_index=0,
        overall=CheckResult.MATCH,
        reason="matching_evidence_found",
        per_evidence=[(source_chunk_id, check)],
    )
    result_row = VerificationResultRow(**slot_verification_values(run_id, claim_id, slot_result))
    check_row = NumericCheckRow(**numeric_check_values(result_row.id, evidence_id, 0, check))

    restored_check = numeric_check_from_row(check_row)
    restored_result = slot_verification_from_rows(result_row, [(source_chunk_id, restored_check)])

    assert restored_result == slot_result
    assert restored_check.tolerance == check.tolerance
    assert restored_check.difference == check.difference
    assert restored_check.claim_slots.value == precision
    assert restored_check.evidence_slots.value == precision


def test_scientific_pack_result_mapper_round_trip():
    result = ValidationResult(
        validator="table_to_text",
        result=CheckResult.INCOMPARABLE,
        assumptions=["context must match"],
        trace=["period slot differs"],
    )
    row = VerificationResultRow(**validation_result_values(uuid4(), uuid4(), 0, result))

    assert validation_result_from_row(row) == result
