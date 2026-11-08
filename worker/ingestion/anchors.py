
import uuid

from domain.schemas import EvidenceChunk


def _k(file_hash: str) -> str:
    return file_hash[:12]


def para_anchor_id(file_hash: str, page: int, idx: int) -> str:
    return f"{_k(file_hash)}:p{page}:para{idx}"


def row_anchor_id(file_hash: str, page: int, table: int, row: int) -> str:
    return f"{_k(file_hash)}:p{page}:t{table}:r{row}"


def cell_anchor_id(
    file_hash: str,
    page: int,
    table: int,
    row: int,
    col: int
) -> str:
    return row_anchor_id(file_hash, page, table, row) + f":c{col}"


def csv_row_anchor_id(file_hash: str, row: int) -> str:
    return f"{_k(file_hash)}:csv:r{row}"


def stable_uuid(*parts) -> uuid.UUID:
    value = "evidencegraph|" + "|".join(str(p) for p in parts)

    return uuid.uuid5(uuid.NAMESPACE_URL, value)


def make_chunk(
    document_id,
    anchor,
    text: str,
    **extra
) -> EvidenceChunk:

    return EvidenceChunk(
        chunk_id=stable_uuid("chunk", anchor.anchor_id),
        document_id=document_id,
        anchor=anchor,
        text=text,
        **extra
    )
