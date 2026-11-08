# domain/schemas.py additions (your part of the contract)
from decimal import Decimal
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class AnchorKind(str, Enum):
    PARAGRAPH = 'paragraph'
    TABLE_ROW = 'table_row'
    TABLE_CELL = 'table_cell'
    CSV_ROW = 'csv_row'


class SourceAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)
    anchor_id: str                      # deterministic, see anchors.py
    document_id: UUID
    kind: AnchorKind
    page: int | None = None
    table_index: int | None = None
    row: int | None = None              # 0 = header row; data rows start at 1
    col: int | None = None
    char_start: int | None = None       # offsets into the page body text
    char_end: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    low_quality: bool = False
    low_quality_reasons: list[str] = Field(default_factory=list)
    extraction_method: str
    parser_version: str


class EvidenceChunk(BaseModel):
    chunk_id: UUID                      # uuid5 of anchor_id
    document_id: UUID
    anchor: SourceAnchor
    text: str                           # whitespace-normalised
    headers: list[str] = Field(default_factory=list)
    caption: str | None = None
    cells: dict[str, str] | None = None  # header -> cell text (table and CSV rows)


class IngestionResult(BaseModel):
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    processing_error: str | None = None  # e.g. 'scanned_pdf_unsupported': Document FAILED, not a claim verdict


class NumericSlots(BaseModel):          # Framework 4.6. None = not established, never guessed
    raw_text: str = ''
    metric: str | None = None
    entity: str | None = None
    value: Decimal | None = None        # sign included
    unit: str | None = None             # 'percent' | 'percentage_point' | 'ratio' | a pint unit
    scale: Decimal | None = None        # 1000000 for 'million'
    period: str | None = None
    comparison_basis: str | None = None
    denominator: str | None = None
    decimals: int | None = None         # digits after the point, as written
    approximate: bool = False
    source_anchor_id: str | None = None


class ClaimType(str, Enum):
    QUANTITATIVE = 'quantitative'
    COMPARATIVE = 'comparative'
    TEMPORAL = 'temporal'
    CITATION = 'citation'
    CATEGORICAL = 'categorical'
    OTHER = 'other'


class Claim(BaseModel):
    claim_id: UUID                      # uuid5 of (file_hash, anchor, offsets, extractor version)
    document_id: UUID
    claim_text: str
    claim_type: ClaimType
    source_anchor_id: str
    char_start: int                     # offsets into the chunk text, not the PDF
    char_end: int
    numeric_slots: list[NumericSlots] = Field(default_factory=list)
    extraction_method: str
    extraction_confidence: float        # rule score, NOT a probability
    low_quality: bool = False


class CheckResult(str, Enum):
    MATCH = 'match'
    MISMATCH = 'mismatch'
    INCOMPARABLE = 'incomparable'
    NOT_APPLICABLE = 'not_applicable'


class NumericCheck(BaseModel):
    result: CheckResult
    claim_slots: NumericSlots
    evidence_slots: NumericSlots
    tolerance: Decimal | None = None
    difference: Decimal | None = None
    failed_slots: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    validator_version: str