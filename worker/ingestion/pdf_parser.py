
import re
from pathlib import Path
from uuid import UUID

import pdfplumber

from domain.schemas import AnchorKind, SourceAnchor, EvidenceChunk
from worker.ingestion.anchors import (
    make_chunk,
    para_anchor_id,
    row_anchor_id
)


PARSER_VERSION = f"pdfplumber-{pdfplumber.__version__}/eg-pdf-1"

MIN_CHARS_PER_PAGE = 40
MAX_EMPTY_FRACTION = 0.3

CAPTION_RE = re.compile(r"^(Table|Tab\.)\s*\d+", re.IGNORECASE)


class ScannedPdfError(Exception):
    """Raised when a PDF has no usable extractable text."""
    pass


def _not_within(bboxes):
    """
    Return a filter function that excludes text objects
    whose centre lies inside a table bounding box.
    """

    def keep(obj):
        vertical_mid = (obj["top"] + obj["bottom"]) / 2
        horizontal_mid = (obj["x0"] + obj["x1"]) / 2

        return not any(
            x0 <= horizontal_mid < x1
            and top <= vertical_mid < bottom
            for x0, top, x1, bottom in bboxes
        )

    return keep


def split_paragraphs(text: str) -> list[tuple[int, int]]:
    """
    Return (start, end) character spans for paragraphs.

    A paragraph ends at:
    1. A blank line.
    2. A short line ending in '.', '?' or '!'.
    """

    lines = text.split("\n")
    max_len = max((len(line) for line in lines), default=0)

    spans = []
    start = None
    position = 0

    for line in lines:
        end = position + len(line)

        if line.strip():

            if start is None:
                start = position

            if (
                line.rstrip().endswith((".", "?", "!"))
                and len(line) < 0.75 * max_len
            ):
                spans.append((start, end))
                start = None

        elif start is not None:
            spans.append((start, position))
            start = None

        position = end + 1

    if start is not None:
        spans.append((start, len(text)))

    return spans


def _table_quality(rows) -> list[str]:
    """Identify common table extraction problems."""

    if not rows:
        return ["empty_table"]

    header = rows[0]
    body = rows[1:]

    reasons = []

    if len(header) < 2:
        reasons.append("single_column")

    if any(
        cell is None or not str(cell).strip()
        for cell in header[1:]
    ):
        reasons.append("empty_header_cell")

    names = [
        str(cell).strip().casefold()
        for cell in header
        if cell is not None and str(cell).strip()
    ]

    if len(set(names)) != len(names):
        reasons.append("duplicate_headers")

    body_cells = [
        cell
        for row in body
        for cell in row
    ]

    if body_cells:
        empty_count = sum(
            cell is None or not str(cell).strip()
            for cell in body_cells
        )

        if empty_count / len(body_cells) > MAX_EMPTY_FRACTION:
            reasons.append("sparse_table")

    return reasons


def _find_caption(page, bbox):
    """
    Look 45 points above and below a table
    for a caption such as 'Table 1'.
    """

    x0, top, x1, bottom = bbox

    regions = [
        (0, max(0, top - 45), page.width, top),
        (0, bottom, page.width, min(page.height, bottom + 45))
    ]

    for region in regions:

        if region[3] - region[1] < 5:
            continue

        cropped_page = page.crop(region)
        extracted_text = cropped_page.extract_text() or ""

        for line in extracted_text.splitlines():
            if CAPTION_RE.match(line.strip()):
                return line.strip()

    return None


def _table_chunks(
    page,
    page_no: int,
    table_index: int,
    table,
    document_id: UUID,
    file_hash: str
) -> list[EvidenceChunk]:

    rows = table.extract()

    if not rows or len(rows) < 2:
        return []

    header = [
        str(cell or "").strip()
        for cell in rows[0]
    ]

    caption = _find_caption(page, table.bbox)
    reasons = _table_quality(rows)

    chunks = []

    for row_index, row in enumerate(rows[1:], start=1):

        cells = {}

        for col_index, (header_name, value) in enumerate(
            zip(header, row)
        ):
            key = header_name or f"col{col_index}"

            # Avoid overwriting duplicate column names.
            if key in cells:
                key = f"{key}#{col_index + 1}"

            cells[key] = str(value or "").strip()

        anchor_id = row_anchor_id(
            file_hash,
            page_no,
            table_index,
            row_index
        )

        anchor = SourceAnchor(
            anchor_id=anchor_id,
            document_id=document_id,
            kind=AnchorKind.TABLE_ROW,
            page=page_no,
            table_index=table_index,
            row=row_index,
            bbox=tuple(table.bbox),
            low_quality=bool(reasons),
            low_quality_reasons=reasons,
            extraction_method="pdfplumber.find_tables",
            parser_version=PARSER_VERSION
        )

        text = (
            (f"{caption} | " if caption else "")
            + " | ".join(
                f"{key}: {value}"
                for key, value in cells.items()
            )
        )

        chunk = make_chunk(
            document_id,
            anchor,
            text,
            headers=header,
            caption=caption,
            cells=cells
        )

        chunks.append(chunk)

    return chunks


def ingest_pdf(
    path: Path,
    document_id: UUID,
    file_hash: str
) -> list[EvidenceChunk]:

    chunks = []

    total_chars = 0
    empty_pages = 0

    with pdfplumber.open(path) as pdf:

        page_count = len(pdf.pages)

        if page_count == 0:
            raise ScannedPdfError("PDF contains no pages")

        for page_no, page in enumerate(pdf.pages, start=1):

            # Extract all page text to assess whether it is scanned.
            raw_text = page.extract_text() or ""

            if not raw_text.strip():
                empty_pages += 1

            total_chars += len(raw_text.strip())

            # Find tables and their bounding boxes.
            tables = page.find_tables()
            bboxes = [table.bbox for table in tables]

            # Exclude table contents from ordinary paragraph extraction.
            if bboxes:
                body_page = page.filter(_not_within(bboxes))
                body_text = body_page.extract_text() or ""
            else:
                body_text = raw_text

            # Extract paragraphs.
            for paragraph_index, (start, end) in enumerate(
                split_paragraphs(body_text)
            ):

                paragraph = " ".join(
                    body_text[start:end].split()
                )

                if not paragraph:
                    continue

                anchor = SourceAnchor(
                    anchor_id=para_anchor_id(
                        file_hash,
                        page_no,
                        paragraph_index
                    ),
                    document_id=document_id,
                    kind=AnchorKind.PARAGRAPH,
                    page=page_no,
                    char_start=start,
                    char_end=end,
                    extraction_method="pdfplumber.extract_text",
                    parser_version=PARSER_VERSION
                )

                chunks.append(
                    make_chunk(
                        document_id,
                        anchor,
                        paragraph
                    )
                )

            # Extract table rows.
            for table_index, table in enumerate(tables):

                table_chunks = _table_chunks(
                    page,
                    page_no,
                    table_index,
                    table,
                    document_id,
                    file_hash
                )

                chunks.extend(table_chunks)

        # Reject scanned/image-only PDFs and mostly empty PDFs.
        empty_fraction = empty_pages / page_count
        average_chars = total_chars / page_count

        if (
            average_chars < MIN_CHARS_PER_PAGE
            or empty_fraction > MAX_EMPTY_FRACTION
        ):
            raise ScannedPdfError(
                "PDF has insufficient extractable text"
            )

    return chunks
