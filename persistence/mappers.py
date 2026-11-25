"""Explicit conversions between domain objects and persistence rows."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from domain.schemas import (
    AnchorKind,
    CheckResult,
    ClaimType,
    NumericCheck,
    NumericSlots,
    SourceAnchor,
)
from domain.schemas import (
    Claim as DomainClaim,
)
from domain.schemas import (
    EvidenceChunk as DomainEvidenceChunk,
)
from domain_packs.scientific_research.pack import ValidationResult
from eg_common.ids import derive_uuid
from persistence.models import (
    ClaimRow,
    EvidenceChunkRow,
    NumericCheckRow,
    SourceLocationRow,
    VerificationResultRow,
)
from worker.verification.numeric import SlotVerification


def source_location_values(anchor: SourceAnchor) -> dict[str, Any]:
    """Map a source anchor to its normalized database columns."""
    return {
        "id": derive_uuid(anchor.document_id, "source_location", anchor.anchor_id),
        "document_id": anchor.document_id,
        "anchor_id": anchor.anchor_id,
        "kind": anchor.kind.value,
        "page": anchor.page,
        "table_index": anchor.table_index,
        "row": anchor.row,
        "col": anchor.col,
        "char_start": anchor.char_start,
        "char_end": anchor.char_end,
        "bbox": list(anchor.bbox) if anchor.bbox is not None else None,
        "low_quality": anchor.low_quality,
        "low_quality_reasons": list(anchor.low_quality_reasons),
        "extraction_method": anchor.extraction_method,
        "parser_version": anchor.parser_version,
    }


def source_anchor_from_row(row: SourceLocationRow) -> SourceAnchor:
    """Rebuild a domain anchor from its normalized persistence row."""
    bbox = (row.bbox[0], row.bbox[1], row.bbox[2], row.bbox[3]) if row.bbox is not None else None
    return SourceAnchor(
        anchor_id=row.anchor_id,
        document_id=row.document_id,
        kind=AnchorKind(row.kind),
        page=row.page,
        table_index=row.table_index,
        row=row.row,
        col=row.col,
        char_start=row.char_start,
        char_end=row.char_end,
        bbox=bbox,
        low_quality=row.low_quality,
        low_quality_reasons=list(row.low_quality_reasons),
        extraction_method=row.extraction_method,
        parser_version=row.parser_version,
    )


def evidence_chunk_values(
    chunk: DomainEvidenceChunk,
    source_location_id: UUID,
    ordinal: int,
) -> dict[str, Any]:
    """Map an evidence chunk while keeping B's chunk ID as a source identifier."""
    return {
        "id": derive_uuid(chunk.document_id, "evidence_chunk", chunk.chunk_id),
        "source_chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "source_location_id": source_location_id,
        "ordinal": ordinal,
        "text": chunk.text,
        "headers": list(chunk.headers),
        "caption": chunk.caption,
        "cells": dict(chunk.cells) if chunk.cells is not None else None,
    }


def evidence_chunk_from_row(
    row: EvidenceChunkRow,
    anchor: SourceAnchor,
) -> DomainEvidenceChunk:
    """Rebuild B's evidence chunk with its original source chunk ID."""
    return DomainEvidenceChunk(
        chunk_id=row.source_chunk_id,
        document_id=row.document_id,
        anchor=anchor,
        text=row.text,
        headers=list(row.headers),
        caption=row.caption,
        cells=dict(row.cells) if row.cells is not None else None,
    )


def claim_values(claim: DomainClaim, source_location_id: UUID) -> dict[str, Any]:
    """Map a claim to a document-scoped persistence ID and preserve B's ID."""
    claim_id = derive_uuid(
        claim.document_id,
        claim.source_anchor_id,
        claim.char_start,
        claim.char_end,
    )
    return {
        "id": claim_id,
        "extractor_claim_id": claim.claim_id,
        "document_id": claim.document_id,
        "source_location_id": source_location_id,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type.value,
        "source_anchor_id": claim.source_anchor_id,
        "char_start": claim.char_start,
        "char_end": claim.char_end,
        "numeric_slots": [slot.model_dump(mode="json") for slot in claim.numeric_slots],
        "extraction_method": claim.extraction_method,
        "extraction_confidence": claim.extraction_confidence,
        "low_quality": claim.low_quality,
    }


def claim_from_row(row: ClaimRow) -> DomainClaim:
    """Rebuild the domain claim, restoring B's original claim identifier."""
    return DomainClaim(
        claim_id=row.extractor_claim_id,
        document_id=row.document_id,
        claim_text=row.claim_text,
        claim_type=ClaimType(row.claim_type),
        source_anchor_id=row.source_anchor_id,
        char_start=row.char_start,
        char_end=row.char_end,
        numeric_slots=[NumericSlots.model_validate(slot) for slot in row.numeric_slots],
        extraction_method=row.extraction_method,
        extraction_confidence=row.extraction_confidence,
        low_quality=row.low_quality,
    )


def slot_verification_values(
    run_id: UUID,
    claim_id: UUID,
    result: SlotVerification,
) -> dict[str, Any]:
    """Map B's aggregate numeric verification result to a run-scoped row."""
    return {
        "id": derive_uuid(run_id, claim_id, "numeric_slot", result.slot_index),
        "run_id": run_id,
        "claim_id": claim_id,
        "result_type": "numeric_slot",
        "result_key": f"slot:{result.slot_index}",
        "result": result.overall.value,
        "reason": result.reason,
        "validator": None,
        "slot_index": result.slot_index,
        "assumptions": [],
        "trace": [],
    }


def validation_result_values(
    run_id: UUID,
    claim_id: UUID,
    index: int,
    result: ValidationResult,
) -> dict[str, Any]:
    """Map a scientific-pack result to a distinct run-scoped result row."""
    return {
        "id": derive_uuid(run_id, claim_id, "domain_validator", index),
        "run_id": run_id,
        "claim_id": claim_id,
        "result_type": "domain_validator",
        "result_key": f"validator:{index:08d}",
        "result": result.result.value,
        "reason": None,
        "validator": result.validator,
        "slot_index": None,
        "assumptions": list(result.assumptions),
        "trace": list(result.trace),
    }


def numeric_check_values(
    verification_result_id: UUID,
    evidence_chunk_id: UUID,
    check_index: int,
    check: NumericCheck,
) -> dict[str, Any]:
    """Map one per-evidence numeric check without converting Decimal values to float."""
    return {
        "id": derive_uuid(verification_result_id, "numeric_check", check_index),
        "verification_result_id": verification_result_id,
        "evidence_chunk_id": evidence_chunk_id,
        "check_index": check_index,
        "result": check.result.value,
        "claim_slots": check.claim_slots.model_dump(mode="json"),
        "evidence_slots": check.evidence_slots.model_dump(mode="json"),
        "tolerance": check.tolerance,
        "difference": check.difference,
        "failed_slots": list(check.failed_slots),
        "trace": list(check.trace),
        "validator_version": check.validator_version,
    }


def numeric_check_from_row(row: NumericCheckRow) -> NumericCheck:
    """Rebuild a numeric check with exact Decimal slot and calculation values."""
    return NumericCheck(
        result=CheckResult(row.result),
        claim_slots=NumericSlots.model_validate(row.claim_slots),
        evidence_slots=NumericSlots.model_validate(row.evidence_slots),
        tolerance=row.tolerance,
        difference=row.difference,
        failed_slots=list(row.failed_slots),
        trace=list(row.trace),
        validator_version=row.validator_version,
    )


def slot_verification_from_rows(
    result_row: VerificationResultRow,
    numeric_checks: list[tuple[UUID, NumericCheck]],
) -> SlotVerification:
    """Rebuild B's slot-level dataclass and its source-chunk-indexed checks."""
    if result_row.result_type != "numeric_slot" or result_row.slot_index is None:
        raise ValueError("result row is not a numeric slot verification")
    return SlotVerification(
        slot_index=result_row.slot_index,
        overall=CheckResult(result_row.result),
        reason=result_row.reason or "",
        per_evidence=numeric_checks,
    )


def validation_result_from_row(row: VerificationResultRow) -> ValidationResult:
    """Rebuild a scientific-pack result from a persisted result row."""
    if row.result_type != "domain_validator" or row.validator is None:
        raise ValueError("result row is not a domain validator result")
    return ValidationResult(
        validator=row.validator,
        result=CheckResult(row.result),
        assumptions=list(row.assumptions),
        trace=list(row.trace),
    )
