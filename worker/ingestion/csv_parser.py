
import csv
from pathlib import Path
from uuid import UUID

from domain.schemas import AnchorKind, EvidenceChunk, SourceAnchor
from .anchors import csv_row_anchor_id, make_chunk


PARSER_VERSION = "csv-stdlib/eg-csv-1"


def ingest_csv(
    path: Path,
    document_id: UUID,
    file_hash: str
) -> list[EvidenceChunk]:

    chunks = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        header = [h.strip() for h in next(reader, [])]

        base_reasons = []

        if not header or any(not h for h in header):
            base_reasons.append("empty_header_cell")

        if len({h.casefold() for h in header}) != len(header):
            base_reasons.append("duplicate_headers")

        for r, row in enumerate(reader, start=1):

            # Skip completely blank rows
            if not any(c.strip() for c in row):
                continue

            reasons = base_reasons.copy()

            if len(row) != len(header):
                reasons.append("ragged_row")

            cells = {
                (h or f"col{i}"): c.strip()
                for i, (h, c) in enumerate(zip(header, row))
            }

            anchor_id = csv_row_anchor_id(file_hash, r)

            anchor = SourceAnchor(
                anchor_id=anchor_id,
                document_id=document_id,
                kind=AnchorKind.CSV_ROW,
                row=r,
                low_quality=bool(reasons),
                low_quality_reasons=reasons,
                extraction_method="csv.reader",
                parser_version=PARSER_VERSION
            )

            text = " | ".join(
                f"{key}: {value}"
                for key, value in cells.items()
            )

            chunk = make_chunk(
                document_id,
                anchor,
                text,
                headers=header,
                cells=cells
            )

            chunks.append(chunk)

    return chunks
