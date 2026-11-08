from decimal import Decimal
from uuid import uuid4

from domain.schemas import (
    AnchorKind,
    EvidenceChunk,
    SourceAnchor,
)
from worker.extraction.evidence_slots import slots_from_chunk


def make_chunk(kind, text="", cells=None, caption=None):
    document_id = uuid4()

    anchor = SourceAnchor(
        anchor_id="test-anchor",
        document_id=document_id,
        kind=kind,
        extraction_method="test",
        parser_version="test",
    )

    return EvidenceChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        anchor=anchor,
        text=text,
        cells=cells,
        caption=caption,
    )


def test_paragraph_chunk_extracts_numeric_slots():
    chunk = make_chunk(
        AnchorKind.PARAGRAPH,
        text="Our model achieves 91.2% accuracy on the test set.",
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) >= 1
    assert any(slot.metric == "accuracy" for slot in slots)
    assert any(slot.value == Decimal("91.2") for slot in slots)


def test_table_extracts_accuracy_and_f1():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={
            "Model": "Ours",
            "Accuracy (%)": "91.2",
            "F1": "0.88",
        },
        caption="Results on the test set",
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) == 2

    accuracy = next(slot for slot in slots if slot.metric == "accuracy")
    f1 = next(slot for slot in slots if slot.metric == "f1")

    assert accuracy.value == Decimal("91.2")
    assert accuracy.unit == "percent"
    assert accuracy.entity == "ours"
    assert accuracy.period == "test"

    assert f1.value == Decimal("0.88")
    assert f1.entity == "ours"


def test_table_uses_caption_period():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={
            "Model": "Baseline",
            "Accuracy (%)": "85.4",
        },
        caption="Performance on the validation set",
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) == 1
    assert slots[0].period == "validation"


def test_table_uses_header_period_over_caption_period():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={
            "Model": "Ours",
            "Accuracy (%) test set": "91.2",
        },
        caption="Results on the validation set",
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) == 1
    assert slots[0].period == "test"


def test_table_skips_empty_cells():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={
            "Model": "Ours",
            "Accuracy (%)": "91.2",
            "F1": "",
        },
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) == 1
    assert slots[0].metric == "accuracy"


def test_table_keeps_main_value_before_error_term():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={
            "Model": "Ours",
            "Accuracy (%)": "91.2 ± 0.3",
        },
    )

    slots = slots_from_chunk(chunk)

    assert len(slots) == 1
    assert slots[0].value == Decimal("91.2")


def test_empty_table_returns_no_slots():
    chunk = make_chunk(
        AnchorKind.TABLE_ROW,
        cells={},
    )

    assert slots_from_chunk(chunk) == []