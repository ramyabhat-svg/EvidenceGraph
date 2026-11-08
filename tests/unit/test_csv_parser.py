
import csv
from uuid import uuid4

from domain.schemas import AnchorKind
from worker.ingestion.csv_parser import ingest_csv


DOCUMENT_ID = uuid4()
FILE_HASH = "abcdef1234567890abcdef"


def create_csv(tmp_path, filename, rows):
    path = tmp_path / filename

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    return path


def test_csv_rows_are_extracted(tmp_path):
    path = create_csv(
        tmp_path,
        "sample.csv",
        [
            ["Model", "Accuracy"],
            ["Model A", "92%"],
            ["Model B", "95%"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert len(chunks) == 2
    assert chunks[0].cells["Model"] == "Model A"
    assert chunks[0].cells["Accuracy"] == "92%"
    assert chunks[1].cells["Model"] == "Model B"


def test_csv_anchor_is_created(tmp_path):
    path = create_csv(
        tmp_path,
        "sample.csv",
        [
            ["Name", "Score"],
            ["Alice", "90"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert chunks[0].anchor.kind == AnchorKind.CSV_ROW
    assert chunks[0].anchor.anchor_id == "abcdef123456:csv:r1"


def test_csv_anchor_is_stable(tmp_path):
    path = create_csv(
        tmp_path,
        "sample.csv",
        [
            ["Name", "Score"],
            ["Alice", "90"]
        ]
    )

    first = ingest_csv(path, DOCUMENT_ID, FILE_HASH)
    second = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert first[0].anchor.anchor_id == second[0].anchor.anchor_id
    assert first[0].chunk_id == second[0].chunk_id


def test_ragged_row_is_flagged(tmp_path):
    path = create_csv(
        tmp_path,
        "ragged.csv",
        [
            ["Name", "Score", "Grade"],
            ["Alice", "90", "A"],
            ["Bob", "80"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert len(chunks) == 2
    assert chunks[0].anchor.low_quality is False
    assert chunks[1].anchor.low_quality is True
    assert "ragged_row" in chunks[1].anchor.low_quality_reasons


def test_duplicate_headers_are_flagged(tmp_path):
    path = create_csv(
        tmp_path,
        "duplicate.csv",
        [
            ["Name", "Score", "Score"],
            ["Alice", "90", "95"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert chunks[0].anchor.low_quality is True
    assert "duplicate_headers" in chunks[0].anchor.low_quality_reasons


def test_blank_rows_are_skipped(tmp_path):
    path = create_csv(
        tmp_path,
        "blank.csv",
        [
            ["Name", "Score"],
            ["Alice", "90"],
            ["", ""],
            ["Bob", "80"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert len(chunks) == 2
    assert chunks[0].cells["Name"] == "Alice"
    assert chunks[1].cells["Name"] == "Bob"


def test_empty_header_cell_is_flagged(tmp_path):
    path = create_csv(
        tmp_path,
        "empty_header.csv",
        [
            ["Name", "", "Grade"],
            ["Alice", "90", "A"]
        ]
    )

    chunks = ingest_csv(path, DOCUMENT_ID, FILE_HASH)

    assert chunks[0].anchor.low_quality is True
    assert "empty_header_cell" in chunks[0].anchor.low_quality_reasons
