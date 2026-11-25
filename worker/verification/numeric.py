
import re
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

import pint

from domain.schemas import (
    Claim,
    CheckResult,
    EvidenceChunk,
    NumericCheck,
    NumericSlots,
)
from worker.extraction.evidence_slots import slots_from_chunk


VALIDATOR_VERSION = "numeric-1"

_ureg = pint.UnitRegistry(non_int_type=Decimal)


@dataclass(frozen=True)
class NumericConfig:
    approx_multiplier: Decimal = Decimal("2")


@dataclass
class SlotVerification:
    slot_index: int
    overall: CheckResult
    reason: str
    per_evidence: list[tuple[UUID, NumericCheck]]
    trace: list[str] = field(default_factory=list)


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^a-z0-9%]+", " ", value.casefold()).strip() or None


def canonical(
    slots: NumericSlots,
) -> tuple[Decimal, str, Decimal]:
    """
    Convert a numeric slot into:
    canonical value, canonical unit family, written precision.
    """

    if slots.value is None:
        raise ValueError("Cannot canonicalize a missing numeric value")

    scale = slots.scale if slots.scale is not None else Decimal(1)

    quantum = Decimal(1).scaleb(-(slots.decimals or 0))

    if slots.unit in ("percent", "ratio"):
        factor = (
            Decimal("0.01")
            if slots.unit == "percent"
            else Decimal(1)
        ) * scale

        return (
            slots.value * factor,
            "fraction",
            quantum * factor,
        )

    if slots.unit == "percentage_point":
        factor = Decimal("0.01") * scale

        return (
            slots.value * factor,
            "percentage_point",
            quantum * factor,
        )

    if slots.unit is None:
        return (
            slots.value * scale,
            "unitless",
            quantum * scale,
        )

    quantity = _ureg.Quantity(
        Decimal(1), slots.unit
    ).to_base_units()

    factor = quantity.magnitude * scale

    return (
        slots.value * factor,
        str(quantity.units),
        quantum * factor,
    )


def compare_slots(
    claim: NumericSlots,
    evidence: NumericSlots,
    config: NumericConfig | None = None,
) -> NumericCheck:

    config = config or NumericConfig()

    trace = []
    failed = []

    def result(
        status: CheckResult,
        tolerance=None,
        difference=None,
    ):
        return NumericCheck(
            result=status,
            claim_slots=claim,
            evidence_slots=evidence,
            tolerance=tolerance,
            difference=difference,
            failed_slots=failed,
            trace=trace,
            validator_version=VALIDATOR_VERSION,
        )

    # A missing numeric value cannot be verified.
    if claim.value is None or evidence.value is None:
        trace.append("Numeric value missing")
        failed.append("value")
        return result(CheckResult.NOT_APPLICABLE)

    # Required contextual slots must agree.
    required = (
        "metric",
        "entity",
        "period",
        "denominator",
        "comparison_basis",
    )

    for field in required:
        claim_value = _norm(getattr(claim, field))
        evidence_value = _norm(getattr(evidence, field))

        if claim_value != evidence_value:
            failed.append(field)

    if claim.metric is None or not _norm(claim.metric):
        if "metric" not in failed:
            failed.append("metric")

    if failed:
        trace.append("Required contextual slots do not agree")
        return result(CheckResult.INCOMPARABLE)

    trace.append("Required contextual slots agree")

    # Convert values into canonical units.
    try:
        claim_value, claim_unit, claim_precision = canonical(claim)
        evidence_value, evidence_unit, evidence_precision = canonical(evidence)

    except (pint.errors.UndefinedUnitError,
            pint.errors.DimensionalityError,
            ValueError) as exc:
        failed.append("unit")
        trace.append(f"Unit conversion unavailable: {exc}")
        return result(CheckResult.INCOMPARABLE)

    trace.append(f"Claim unit family: {claim_unit}")
    trace.append(f"Evidence unit family: {evidence_unit}")

    if claim_unit != evidence_unit:
        failed.append("unit")
        trace.append("Unit families are incompatible")
        return result(CheckResult.INCOMPARABLE)

    difference = abs(claim_value - evidence_value)

    # Half the coarser written precision.
    tolerance = max(
        claim_precision,
        evidence_precision,
    ) / Decimal(2)

    if claim.approximate:
        tolerance *= config.approx_multiplier
        trace.append("Approximation tolerance applied")

    trace.append(f"Canonical claim value: {claim_value}")
    trace.append(f"Canonical evidence value: {evidence_value}")
    trace.append(f"Difference: {difference}")
    trace.append(f"Allowed tolerance: {tolerance}")

    if difference <= tolerance:
        trace.append("Difference is within tolerance")
        return result(
            CheckResult.MATCH,
            tolerance,
            difference,
        )

    failed.append("value")
    trace.append("Difference exceeds tolerance")

    return result(
        CheckResult.MISMATCH,
        tolerance,
        difference,
    )


def verify_numeric_claim(
    claim: Claim,
    evidence_chunks: list[EvidenceChunk],
    config: NumericConfig | None = None,
) -> list[SlotVerification]:

    config = config or NumericConfig()

    output = []

    for index, claim_slot in enumerate(claim.numeric_slots):

        # A claim without a usable number cannot be checked.
        if claim_slot.value is None:
            output.append(
                SlotVerification(
                    slot_index=index,
                    overall=CheckResult.NOT_APPLICABLE,
                    reason="claim_value_missing",
                    per_evidence=[],
                )
            )
            continue

        comparisons = []
        evidence_slots_by_chunk: list[tuple[EvidenceChunk, NumericSlots]] = []

        for chunk in evidence_chunks:
            evidence_slots = slots_from_chunk(chunk)

            for evidence_slot in evidence_slots:
                evidence_slots_by_chunk.append((chunk, evidence_slot))
                check = compare_slots(
                    claim_slot,
                    evidence_slot,
                    config,
                )

                comparisons.append((chunk.chunk_id, check))

        derived = _verify_explicit_difference(
            claim_slot, evidence_slots_by_chunk, config
        )
        aggregate_trace: list[str] = []
        if derived is not None:
            derived_check, support = derived
            comparisons.extend((chunk_id, derived_check) for chunk_id in support)
            aggregate_trace.extend(derived_check.trace)

        if not comparisons:
            output.append(
                SlotVerification(
                    slot_index=index,
                    overall=CheckResult.INCOMPARABLE,
                    reason="no_numeric_evidence",
                    per_evidence=[],
                    trace=aggregate_trace,
                )
            )
            continue

        statuses = [
            check.result for _, check in comparisons
        ]

        has_match = CheckResult.MATCH in statuses
        has_mismatch = CheckResult.MISMATCH in statuses

        if has_match and has_mismatch:
            overall = CheckResult.INCOMPARABLE
            reason = "conflicting_evidence"

        elif has_match:
            overall = CheckResult.MATCH
            reason = "matching_evidence_found"

        elif has_mismatch:
            overall = CheckResult.MISMATCH
            reason = "mismatching_evidence_found"

        else:
            overall = CheckResult.INCOMPARABLE

            failed_slots = sorted({
                field
                for _, check in comparisons
                for field in check.failed_slots
            })

            reason = (
                "incompatible_slots:" + ",".join(failed_slots)
                if failed_slots
                else "no_comparable_evidence"
            )

        output.append(
            SlotVerification(
                slot_index=index,
                overall=overall,
                reason=reason,
                per_evidence=comparisons,
                trace=aggregate_trace,
            )
        )

    return output


def _verify_explicit_difference(
    claim: NumericSlots,
    evidence: list[tuple[EvidenceChunk, NumericSlots]],
    config: NumericConfig,
) -> tuple[NumericCheck, list[UUID]] | None:
    """Derive an explicit difference only from context-compatible endpoint values."""
    if (
        claim.value is None
        or claim.entity is None
        or claim.comparison_basis is None
        or claim.metric is None
        or claim.difference_kind is None
    ):
        return None
    current_entity = _norm(claim.entity)
    baseline_entity = _norm(claim.comparison_basis)
    candidates: list[tuple[EvidenceChunk, NumericSlots]] = []
    for chunk, slot in evidence:
        if (
            slot.value is None
            or _norm(slot.metric) != _norm(claim.metric)
            or _norm(slot.period) != _norm(claim.period)
            or _norm(slot.denominator) != _norm(claim.denominator)
        ):
            continue
        candidates.append((chunk, slot))

    for current_chunk, current in candidates:
        if _norm(current.entity) != current_entity:
            continue
        for baseline_chunk, baseline in candidates:
            if _norm(baseline.entity) != baseline_entity:
                continue
            if current is baseline:
                continue
            same_source = current_chunk.chunk_id == baseline_chunk.chunk_id
            if not same_source and claim.unit in {"percent", "percentage_point"}:
                if claim.denominator is None:
                    continue
            if current.unit != baseline.unit or current.scale != baseline.scale:
                continue
            if claim.unit == "percentage_point":
                if current.unit not in {"percent", "ratio"}:
                    continue
                factor = Decimal("0.01") if current.unit == "percent" else Decimal(1)
                value = (current.value * factor - baseline.value * factor) * Decimal(100)
            elif claim.difference_kind == "relative":
                if current.unit != baseline.unit or baseline.value == 0:
                    continue
                value = (current.value - baseline.value) / abs(baseline.value) * Decimal(100)
                if claim.unit != "percent":
                    continue
            else:
                if current.unit != baseline.unit or current.unit in {"percent", "ratio"}:
                    continue
                value = current.value - baseline.value
                if claim.unit != current.unit:
                    continue
            derived_slot = claim.model_copy(
                update={"raw_text": "derived from explicitly matched endpoints", "value": value}
            )
            check = compare_slots(claim, derived_slot, config)
            check.trace.insert(
                0,
                f"Derived {claim.difference_kind} difference from {current.value} "
                f"({current.entity}) and {baseline.value} ({baseline.entity})",
            )
            return check, list(dict.fromkeys((current_chunk.chunk_id, baseline_chunk.chunk_id)))
    return None
