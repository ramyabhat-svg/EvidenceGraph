
from uuid import uuid4

import pytest

import worker.ingestion.pdf_parser as parser
from worker.ingestion.pdf_parser import (
    split_paragraphs,
    _table_quality,
    _table_chunks,
    ingest_pdf,
    ScannedPdfError
)

from domain.schemas import AnchorKind


FILE_HASH = "abcdef1234567890abcdef"


class FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakePage:
    width = 600
    height = 800

    def __init__(self, text, tables=None):
        self.text = text
        self.tables = tables or []

    def extract_text(self):
        return self.text

    def find_tables(self):
        return self.tables

    def filter(self, function):
        return self

    def crop(self, region):
        return FakeCrop()


class FakeCrop:
    def extract_text(self):
        return "Table 1: Model Results"


class FakeTable:
    bbox = (50, 100, 500, 300)

    def extract(self):
        return [
            ["Model", "Accuracy"],
            ["Model A", "92%"],
            ["Model B", "95%"]
        ]


def test_split_paragraphs():
    text = (
        "This is the first paragraph.\n"
        "\n"
        "This is the second paragraph with more text."
    )

    spans = split_paragraphs(text)

    assert len(spans) == 2

    first = text[spans[0][0]:spans[0][1]]
    second = text[spans[1][0]:spans[1][1]]

    assert first == "This is the first paragraph."
    assert second == "This is the second paragraph with more text."


def test_table_quality_detects_empty_header():
    rows = [
        ["Model", "", "Year"],
        ["A", "90%", "2024"]
    ]

    reasons = _table_quality(rows)

    assert "empty_header_cell" in reasons


def test_table_chunks_extract_rows_and_caption():
    document_id = uuid4()
    page = FakePage("This is some sample page text with enough characters.")

    table = FakeTable()

    chunks = _table_chunks(
        page,
        1,
        0,
        table,
        document_id,
        FILE_HASH
    )

    assert len(chunks) == 2

    assert chunks[0].anchor.kind == AnchorKind.TABLE_ROW
    assert chunks[0].anchor.page == 1

    assert chunks[0].caption == "Table 1: Model Results"
    assert chunks[0].cells["Model"] == "Model A"
    assert chunks[0].cells["Accuracy"] == "92%"

    assert "Table 1: Model Results" in chunks[0].text


def test_pdf_ingestion_extracts_paragraphs(monkeypatch, tmp_path):
    text = (
        "The proposed model achieved an accuracy of 95% "
        "on the test dataset.\n\n"
        "The results demonstrate improved performance "
        "compared with the previous model."
    )

    page = FakePage(text)

    fake_pdf = FakePDF([page])

    monkeypatch.setattr(
        parser.pdfplumber,
        "open",
        lambda path: fake_pdf
    )

    chunks = ingest_pdf(
        tmp_path / "sample.pdf",
        uuid4(),
        FILE_HASH
    )

    assert len(chunks) == 2
    assert chunks[0].anchor.kind == AnchorKind.PARAGRAPH
    assert chunks[0].anchor.page == 1
    assert "95%" in chunks[0].text


def test_pdf_anchor_is_deterministic(monkeypatch, tmp_path):
    text = (
        "The proposed system achieved excellent performance "
        "during the evaluation process."
    )

    fake_pdf = FakePDF([FakePage(text)])

    monkeypatch.setattr(
        parser.pdfplumber,
        "open",
        lambda path: fake_pdf
    )

    document_id = uuid4()

    first = ingest_pdf(
        tmp_path / "sample.pdf",
        document_id,
        FILE_HASH
    )

    second = ingest_pdf(
        tmp_path / "sample.pdf",
        document_id,
        FILE_HASH
    )

    assert first[0].anchor.anchor_id == second[0].anchor.anchor_id
    assert first[0].chunk_id == second[0].chunk_id


def test_scanned_pdf_raises_error(monkeypatch, tmp_path):
    fake_pdf = FakePDF([FakePage("")])

    monkeypatch.setattr(
        parser.pdfplumber,
        "open",
        lambda path: fake_pdf
    )

    with pytest.raises(ScannedPdfError):
        ingest_pdf(
            tmp_path / "scanned.pdf",
            uuid4(),
            FILE_HASH
        )
