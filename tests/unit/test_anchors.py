
from uuid import uuid4

from worker.ingestion.anchors import (
    para_anchor_id,
    row_anchor_id,
    cell_anchor_id,
    csv_row_anchor_id,
    stable_uuid,
    make_chunk
)

from domain.schemas import AnchorKind, SourceAnchor


FILE_HASH = "abcdef1234567890abcdef"
DOCUMENT_ID = uuid4()


def test_paragraph_anchor():
    a1 = para_anchor_id(FILE_HASH, 2, 0)
    a2 = para_anchor_id(FILE_HASH, 2, 0)

    assert a1 == a2
    assert a1 == "abcdef123456:p2:para0"


def test_table_row_anchor():
    anchor = row_anchor_id(FILE_HASH, 3, 1, 4)

    assert anchor == "abcdef123456:p3:t1:r4"


def test_table_cell_anchor():
    anchor = cell_anchor_id(FILE_HASH, 3, 1, 4, 2)

    assert anchor == "abcdef123456:p3:t1:r4:c2"


def test_csv_anchor():
    anchor = csv_row_anchor_id(FILE_HASH, 10)

    assert anchor == "abcdef123456:csv:r10"


def test_anchor_ids_are_unique():
    ids = {
        para_anchor_id(FILE_HASH, 1, 0),
        para_anchor_id(FILE_HASH, 1, 1),
        para_anchor_id(FILE_HASH, 2, 0),
        row_anchor_id(FILE_HASH, 1, 0, 1),
        csv_row_anchor_id(FILE_HASH, 1)
    }

    assert len(ids) == 5


def test_stable_uuid():
    id1 = stable_uuid("chunk", "anchor1")
    id2 = stable_uuid("chunk", "anchor1")

    assert id1 == id2


def test_make_chunk():
    anchor = SourceAnchor(
        anchor_id=para_anchor_id(FILE_HASH, 1, 0),
        document_id=DOCUMENT_ID,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=50,
        extraction_method="pdfplumber.extract_text",
        parser_version="test-version"
    )

    chunk = make_chunk(
        DOCUMENT_ID,
        anchor,
        "This is a sample paragraph."
    )

    assert chunk.document_id == DOCUMENT_ID
    assert chunk.anchor.anchor_id == anchor.anchor_id
    assert chunk.text == "This is a sample paragraph."
