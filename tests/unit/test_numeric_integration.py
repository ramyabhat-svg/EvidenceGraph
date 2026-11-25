
from uuid import uuid4
from decimal import Decimal

from domain.schemas import (
    AnchorKind,
    CheckResult,
    Claim,
    ClaimType,
    EvidenceChunk,
    NumericSlots,
    SourceAnchor,
)
from worker.verification.numeric import verify_numeric_claim


def make_claim(value="91.2", period="test"):
    document_id = uuid4()

    return Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="Our model achieves 91.2% accuracy on the test set.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id="claim-anchor",
        char_start=0,
        char_end=55,
        numeric_slots=[
            NumericSlots(
                value=Decimal(value),
                metric="accuracy",
                entity="ours",
                unit="percent",
                period=period,
                decimals=1,
            )
        ],
        extraction_method="test",
        extraction_confidence=0.9,
    )


def make_evidence(value, period="test"):
    document_id = uuid4()
    anchor = SourceAnchor(
        anchor_id=f"evidence-{uuid4()}",
        document_id=document_id,
        kind=AnchorKind.TABLE_ROW,
        extraction_method="test",
        parser_version="test",
    )

    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text=f"Ours {value}",
        caption=f"Results on the {period} set",
        cells={
            "Model": "Ours",
            "Accuracy (%)": value,
        },
    )


def test_claim_matches_evidence():
    result = verify_numeric_claim(
        make_claim(),
        [make_evidence("91.2")],
    )

    assert len(result) == 1
    assert result[0].overall == CheckResult.MATCH
    assert result[0].reason == "matching_evidence_found"


def test_claim_mismatches_evidence():
    result = verify_numeric_claim(
        make_claim(),
        [make_evidence("85.4")],
    )

    assert result[0].overall == CheckResult.MISMATCH
    assert result[0].reason == "mismatching_evidence_found"


def test_conflicting_evidence_is_incomparable():
    result = verify_numeric_claim(
        make_claim(),
        [
            make_evidence("91.2"),
            make_evidence("85.4"),
        ],
    )

    assert result[0].overall == CheckResult.INCOMPARABLE
    assert result[0].reason == "conflicting_evidence"


def test_different_period_is_incomparable():
    result = verify_numeric_claim(
        make_claim(period="test"),
        [make_evidence("91.2", period="training")],
    )

    assert result[0].overall == CheckResult.INCOMPARABLE


def test_no_evidence_is_incomparable():
    result = verify_numeric_claim(
        make_claim(),
        [],
    )

    assert result[0].overall == CheckResult.INCOMPARABLE
    assert result[0].reason == "no_numeric_evidence"


def test_missing_claim_value_is_not_applicable():
    claim = make_claim()
    claim.numeric_slots[0].value = None

    result = verify_numeric_claim(claim, [make_evidence("91.2")])

    assert result[0].overall == CheckResult.NOT_APPLICABLE
    assert result[0].reason == "claim_value_missing"


def test_evidence_comparison_details_are_preserved():
    result = verify_numeric_claim(
        make_claim(),
        [make_evidence("91.2")],
    )

    assert len(result[0].per_evidence) == 1

    evidence_id, numeric_check = result[0].per_evidence[0]

    assert evidence_id is not None
    assert numeric_check.result == CheckResult.MATCH
    assert numeric_check.validator_version == "numeric-1"


def test_percentage_point_difference_can_use_two_separate_endpoint_passages():
    """A contextualized A/B comparison is derived only from matching endpoints."""
    document_id = uuid4()
    claim = Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="Configuration B's relevant-result rate was 10 percentage points higher.",
        claim_type=ClaimType.COMPARATIVE,
        source_anchor_id="claim",
        char_start=0,
        char_end=78,
        numeric_slots=[NumericSlots(
            raw_text="10 percentage points", value=Decimal("10"), unit="percentage_point",
            metric="relevant_result_rate", entity="Configuration B",
            comparison_basis="Configuration A", period="test", denominator="100 queries", decimals=0,
            difference_kind="absolute",
        )],
        extraction_method="test",
        extraction_confidence=0.9,
    )
    endpoints = [
        ("Configuration B had a relevant-result rate of 90% on the test set out of 100 queries.", "b"),
        ("Configuration A had a relevant-result rate of 80% on the test set out of 100 queries.", "a"),
    ]
    evidence = []
    for text, suffix in endpoints:
        anchor = SourceAnchor(
            anchor_id=suffix, document_id=document_id, kind=AnchorKind.PARAGRAPH,
            extraction_method="test", parser_version="test",
        )
        evidence.append(EvidenceChunk(
            chunk_id=uuid4(), document_id=document_id, anchor=anchor, text=text,
        ))
    result = verify_numeric_claim(claim, evidence)[0]
    assert result.overall == CheckResult.MATCH
    assert result.reason == "matching_evidence_found"
    assert result.trace and "Derived absolute difference" in result.trace[0]
