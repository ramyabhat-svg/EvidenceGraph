from decimal import Decimal

from pydantic import BaseModel, Field

from domain.schemas import (
    CheckResult,
    Claim,
    EvidenceChunk,
    NumericCheck,
    NumericSlots,
)
from worker.extraction.evidence_slots import slots_from_chunk
from worker.verification.numeric import (
    NumericConfig,
    canonical,
    compare_slots,
    verify_numeric_claim,
)


GROWTH_WORDS = (
    "grew", "growth", "increase", "decrease", "improv", "reduc",
)

GROWTH_ASSUMPTIONS = [
    "current and previous differ only in period",
    "same unit and scale on both values",
    "growth is relative: (current - previous) / previous * 100",
]


class ValidationResult(BaseModel):
    validator: str
    result: CheckResult
    assumptions: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


def growth_pct(current: Decimal, previous: Decimal) -> Decimal:
    """Calculate relative percentage growth."""
    if previous == 0:
        raise ZeroDivisionError("previous value is zero")

    return (current - previous) / previous * Decimal(100)


def _same_fields(
    first: NumericSlots,
    second: NumericSlots,
    fields: tuple[str, ...],
) -> bool:
    return all(
        getattr(first, field) == getattr(second, field)
        for field in fields
    )


def check_growth(
    claimed: NumericSlots,
    current: NumericSlots,
    previous: NumericSlots,
    cfg: NumericConfig | None = None,
) -> ValidationResult:
    """Check a claimed relative growth against two evidence values."""

    required = (
        "metric",
        "entity",
        "denominator",
        "comparison_basis",
        "unit",
        "scale",
    )

    differing = [
        field
        for field in required
        if getattr(current, field) != getattr(previous, field)
    ]

    if (
        differing
        or claimed.unit != "percent"
        or current.period is None
        or previous.period is None
        or current.period == previous.period
        or claimed.value is None
        or current.value is None
        or previous.value is None
        or previous.value == 0
    ):
        return ValidationResult(
            validator="arithmetic_growth",
            result=CheckResult.INCOMPARABLE,
            assumptions=GROWTH_ASSUMPTIONS,
            trace=[f"Not computable; differing slots: {differing}"],
        )

    derived_value = growth_pct(current.value, previous.value)

    derived = claimed.model_copy(
        update={
            "raw_text": "derived growth",
            "value": derived_value,
            "unit": "percent",
            "scale": None,
            "decimals": 6,
            "approximate": False,
        }
    )

    check = compare_slots(claimed, derived, cfg)

    trace = [
        (
            f"Growth = ({current.value} - {previous.value}) "
            f"/ {previous.value} * 100 = {derived_value}"
        )
    ] + check.trace

    return ValidationResult(
        validator="arithmetic_growth",
        result=check.result,
        assumptions=GROWTH_ASSUMPTIONS,
        trace=trace,
    )


def check_percentage_point_difference(
    claimed: NumericSlots,
    current: NumericSlots,
    previous: NumericSlots,
    cfg: NumericConfig | None = None,
) -> ValidationResult:
    """Check an absolute percentage-point difference, not relative growth."""

    if (
        claimed.unit != "percentage_point"
        or current.unit not in ("percent", "ratio")
        or previous.unit not in ("percent", "ratio")
        or current.period is None
        or previous.period is None
        or current.period == previous.period
        or current.value is None
        or previous.value is None
        or claimed.value is None
        or not _same_fields(
            current,
            previous,
            (
                "metric",
                "entity",
                "denominator",
                "comparison_basis",
                "unit",
                "scale",
            ),
        )
    ):
        return ValidationResult(
            validator="arithmetic_growth",
            result=CheckResult.INCOMPARABLE,
            assumptions=[
                "current and previous differ only in period",
                "percentage-point difference is absolute, not relative",
            ],
            trace=["Percentage-point difference is not computable"],
        )

    scale = current.scale if current.scale is not None else Decimal(1)
    factor = Decimal("0.01") if current.unit == "percent" else Decimal(1)

    current_fraction = current.value * scale * factor
    previous_fraction = previous.value * scale * factor

    difference_pp = (
        current_fraction - previous_fraction
    ) * Decimal(100)

    derived = claimed.model_copy(
        update={
            "raw_text": "derived percentage-point difference",
            "value": difference_pp,
            "unit": "percentage_point",
            "scale": None,
            "decimals": 6,
            "approximate": False,
        }
    )

    check = compare_slots(claimed, derived, cfg)

    return ValidationResult(
        validator="arithmetic_growth",
        result=check.result,
        assumptions=[
            "current and previous differ only in period",
            "percentage-point difference is absolute, not relative",
        ],
        trace=[
            (
                f"Difference = ({current.value} - {previous.value}) "
                f"after unit normalization = {difference_pp} percentage points"
            )
        ] + check.trace,
    )


def scale_hint(check: NumericCheck) -> str | None:
    """
    Explain a mismatch that looks like a power-of-ten scale slip.
    This is only a hint; it never changes the check result.
    """
    if check.result != CheckResult.MISMATCH:
        return None

    claim_value = canonical(check.claim_slots)[0]
    evidence_value = canonical(check.evidence_slots)[0]

    if (
        claim_value == 0
        or evidence_value == 0
        or (claim_value > 0) != (evidence_value > 0)
    ):
        return None

    ratio = claim_value / evidence_value
    exponent = ratio.log10()

    if (
        exponent != 0
        and abs(exponent - exponent.to_integral_value())
        < Decimal("1e-9")
    ):
        return (
            f"Claim is 10^{int(exponent)} times the evidence: "
            "possible unit or scale slip"
        )

    return None


class ScientificResearchPack:
    name = "scientific_research"
    version = "0.1.0"

    def claim_patterns(self) -> list:
        # MVP: claim patterns live in the extraction module and lexicon.
        return []

    def applicable_validators(self, claim: Claim) -> list[str]:
        names = [
            "table_to_text",
            "unit_scale",
            "period_condition",
        ]

        if any(word in claim.claim_text.lower() for word in GROWTH_WORDS):
            names.append("arithmetic_growth")

        return names

    def validate(
        self,
        claim: Claim,
        evidence: list[EvidenceChunk],
    ) -> list[ValidationResult]:

        output = []

        # 1. Ordinary claim-to-table/CSV numeric verification.
        slot_results = verify_numeric_claim(claim, evidence)

        for slot_result in slot_results:
            output.append(
                ValidationResult(
                    validator="table_to_text",
                    result=slot_result.overall,
                    trace=[
                        f"Slot {slot_result.slot_index}: "
                        f"{slot_result.overall.value} "
                        f"({slot_result.reason})"
                    ],
                )
            )

            # 2. Additional explanations for individual evidence checks.
            for _, check in slot_result.per_evidence:
                hint = scale_hint(check)

                if hint:
                    output.append(
                        ValidationResult(
                            validator="unit_scale",
                            result=check.result,
                            assumptions=["all other slots match"],
                            trace=check.trace + [hint],
                        )
                    )

                if check.failed_slots == ["period"]:
                    output.append(
                        ValidationResult(
                            validator="period_condition",
                            result=check.result,
                            assumptions=[
                                "same metric and entity, different period"
                            ],
                            trace=check.trace,
                        )
                    )

        # 3. Arithmetic growth / percentage-point validation.
        if not any(
            word in claim.claim_text.lower()
            for word in GROWTH_WORDS
        ):
            return output

        evidence_slots = []

        for chunk in evidence:
            for slot in slots_from_chunk(chunk):
                evidence_slots.append(slot)

        for claim_slot in claim.numeric_slots:
            pairs = []

            for current in evidence_slots:
                for previous in evidence_slots:
                    if current is previous:
                        continue

                    if (
                        current.value is None
                        or previous.value is None
                        or current.period is None
                        or previous.period is None
                        or current.period == previous.period
                    ):
                        continue

                    if not _same_fields(
                        current,
                        previous,
                        (
                            "metric",
                            "entity",
                            "denominator",
                            "comparison_basis",
                            "unit",
                            "scale",
                        ),
                    ):
                        continue

                    if not _same_fields(
                        claim_slot,
                        current,
                        ("metric", "entity", "denominator", "comparison_basis"),
                    ):
                        continue

                    pairs.append((current, previous))

            if not pairs:
                output.append(
                    ValidationResult(
                        validator="arithmetic_growth",
                        result=CheckResult.INCOMPARABLE,
                        assumptions=GROWTH_ASSUMPTIONS,
                        trace=[
                            "No comparable current/previous evidence pair found"
                        ],
                    )
                )
                continue

            for current, previous in pairs:
                if claim_slot.unit == "percentage_point":
                    result = check_percentage_point_difference(
                        claim_slot, current, previous
                    )
                else:
                    result = check_growth(
                        claim_slot, current, previous
                    )

                output.append(result)

        return output