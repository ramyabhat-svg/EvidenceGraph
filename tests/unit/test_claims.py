
from uuid import uuid4
from decimal import Decimal

import pytest

from domain.schemas import (
    AnchorKind,
    ClaimType,
    EvidenceChunk,
    SourceAnchor,
)
from worker.extraction.claims import extract_claims


DOCUMENT_ID = uuid4()
FILE_HASH = "abcdef1234567890abcdef1234567890"


def make_chunk(text, kind=AnchorKind.PARAGRAPH, low_quality=False):
    anchor = SourceAnchor(
        anchor_id="abcdef123456:p1:para0",
        document_id=DOCUMENT_ID,
        kind=kind,
        page=1,
        extraction_method="test",
        parser_version="test-1",
        low_quality=low_quality,
    )

    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=DOCUMENT_ID,
        anchor=anchor,
        text=text,
    )


# 30 sentence-level examples.
# True means one claim should be extracted.
CASES = [
    ("Model A achieves 91% accuracy.", True),
    ("The accuracy was 92.5%.", True),
    ("Our model obtains 0.95 F1.", True),
    ("The proposed method reaches 88% precision.", True),
    ("The recall increased to 90%.", True),
    ("The model reports an AUC of 0.97.", True),
    ("The RMSE was 2.4.", True),
    ("The MAE decreased to 1.2.", True),
    ("Model A outperforms Model B by 3.4 points.", True),
    ("The result is higher than the baseline by 2.1.", True),
    ("The error was lower by 1.5.", True),
    ("Our approach improves accuracy by 4%.", True),
    ("The performance increased by 3.2 percentage points.", True),
    ("The score is better than the previous result by 5.", True),
    ("The result is worse than Model B by 2.3.", True),
    ("Model A performs better versus Model B by 1.2.", True),
    ("Accuracy on the test set reached 94%.", True),
    ("The model has 2.1M parameters and 95% accuracy.", True),
    ("Latency decreased by 120 ms.", True),
    ("The model achieved an F1 score of 0.91.", True),
    ("Table 3 reports an accuracy value of 91%.", True),
    ("Tab. 2 shows a recall of 0.88.", True),
    ("The proposed model achieves 91.2% accuracy.", True),
    ("Our method obtains 0.89 AUC on the test set.", True),
    ("The baseline has an accuracy of 85%.", True),
    ("The experiment was conducted in 2024.", False),
    ("There were 500 samples in the dataset.", False),
    ("The proposed method was evaluated on a dataset.", False),
    ("The system uses Python and FastAPI.", False),
    ("The experiment used 5 datasets and 3 machines.", False),
]


@pytest.mark.parametrize(
    "sentence, should_extract",
    CASES,
)
def test_claim_extraction_cases(sentence, should_extract):
    chunk = make_chunk(sentence)

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == (1 if should_extract else 0)


def test_claim_text_matches_original_sentence():
    text = "The proposed model achieves 95.2% accuracy on the test set."
    chunk = make_chunk(text)

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1
    assert claims[0].claim_text == text


def test_claim_character_offsets_are_correct():
    text = "Introduction sentence. Model A achieves 95% accuracy."
    chunk = make_chunk(text)

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1

    claim = claims[0]
    assert text[claim.char_start:claim.char_end] == claim.claim_text
    assert claim.char_start == text.index("Model A")


def test_multiple_sentences_are_split_into_separate_claims():
    text = (
        "Model A achieves 95% accuracy. "
        "Model B obtains 90% accuracy."
    )
    chunk = make_chunk(text)

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 2
    assert claims[0].claim_text == "Model A achieves 95% accuracy."
    assert claims[1].claim_text == "Model B obtains 90% accuracy."


def test_comparative_claim_type():
    chunk = make_chunk("Model A outperforms Model B by 3.4 points.")

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1
    assert claims[0].claim_type == ClaimType.COMPARATIVE


def test_quantitative_claim_type():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1
    assert claims[0].claim_type == ClaimType.QUANTITATIVE


def test_numeric_slots_are_attached_to_claim():
    chunk = make_chunk("Model A achieves 95.2% accuracy.")

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1
    assert len(claims[0].numeric_slots) == 1
    assert claims[0].numeric_slots[0].value == Decimal("95.2")
    assert claims[0].numeric_slots[0].metric == "accuracy"


def test_source_anchor_is_attached_to_numeric_slots():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    claims = extract_claims([chunk], FILE_HASH)

    assert claims[0].source_anchor_id == chunk.anchor.anchor_id
    assert (
        claims[0].numeric_slots[0].source_anchor_id
        == chunk.anchor.anchor_id
    )


def test_non_paragraph_chunks_are_ignored():
    csv_chunk = make_chunk(
        "Model A achieves 95% accuracy.",
        kind=AnchorKind.CSV_ROW,
    )

    claims = extract_claims([csv_chunk], FILE_HASH)

    assert claims == []


def test_low_quality_flag_is_preserved():
    chunk = make_chunk(
        "Model A achieves 95% accuracy.",
        low_quality=True,
    )

    claims = extract_claims([chunk], FILE_HASH)

    assert len(claims) == 1
    assert claims[0].low_quality is True


def test_claim_ids_are_deterministic():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    first = extract_claims([chunk], FILE_HASH)
    second = extract_claims([chunk], FILE_HASH)

    assert first[0].claim_id == second[0].claim_id


def test_claim_ids_change_when_file_hash_changes():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    first = extract_claims([chunk], FILE_HASH)
    second = extract_claims([chunk], "different-file-hash")

    assert first[0].claim_id != second[0].claim_id


def test_claim_has_extractor_version():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    claims = extract_claims([chunk], FILE_HASH)

    assert claims[0].extraction_method == "rules-1"


def test_claim_confidence_is_between_zero_and_one():
    chunk = make_chunk("Model A achieves 95% accuracy.")

    claims = extract_claims([chunk], FILE_HASH)

    assert 0.0 <= claims[0].extraction_confidence <= 1.0


def test_empty_input_returns_empty_list():
    assert extract_claims([], FILE_HASH) == []


def test_output_is_sorted_by_source_anchor_and_position():
    first = make_chunk("Model A achieves 95% accuracy.")
    second = make_chunk("Model B achieves 90% accuracy.")

    claims = extract_claims([second, first], FILE_HASH)

    keys = [
        (claim.source_anchor_id, claim.char_start)
        for claim in claims
    ]

    assert keys == sorted(keys)
