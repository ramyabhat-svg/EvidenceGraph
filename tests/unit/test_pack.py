
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.schemas import (
    CheckResult,
    Claim,
    ClaimType,
    NumericSlots,
)
from domain_packs.scientific_research.pack import (
    ScientificResearchPack,
    growth_pct,
    check_growth,
    check_percentage_point_difference,
    scale_hint,
)
from worker.verification.numeric import compare_slots


def make_slots(
    value,
    period="test",
    unit="percent",
    decimals=1,
):
    return NumericSlots(
        value=Decimal(str(value)),
        metric="accuracy",
        entity="ours",
        unit=unit,
        period=period,
        decimals=decimals,
    )


def test_growth_pct():
    assert growth_pct(Decimal("120"), Decimal("100")) == Decimal("20")


def test_growth_pct_decrease():
    assert growth_pct(Decimal("80"), Decimal("100")) == Decimal("-20")


def test_growth_pct_zero_previous():
    with pytest.raises(ZeroDivisionError):
        growth_pct(Decimal("100"), Decimal("0"))


def test_check_growth_match():
    claimed = make_slots("20.0")
    current = make_slots("120", period="2024", decimals=0)
    previous = make_slots("100", period="2023", decimals=0)

    result = check_growth(claimed, current, previous)

    assert result.validator == "arithmetic_growth"
    assert result.result == CheckResult.MATCH


def test_check_growth_mismatch():
    claimed = make_slots("30.0")
    current = make_slots("120", period="2024", decimals=0)
    previous = make_slots("100", period="2023", decimals=0)

    result = check_growth(claimed, current, previous)

    assert result.result == CheckResult.MISMATCH


def test_check_growth_same_period_is_incomparable():
    claimed = make_slots("20.0")
    current = make_slots("120", period="2024")
    previous = make_slots("100", period="2024")

    result = check_growth(claimed, current, previous)

    assert result.result == CheckResult.INCOMPARABLE


def test_percentage_point_difference_match():
    claimed = make_slots(
        "0.5",
        unit="percentage_point",
    )
    current = make_slots("90.2", period="2024")
    previous = make_slots("89.7", period="2023")

    result = check_percentage_point_difference(
        claimed, current, previous
    )

    assert result.result == CheckResult.MATCH


def test_percentage_point_difference_is_not_relative_growth():
    claimed = make_slots(
        "0.5",
        unit="percentage_point",
    )
    current = make_slots("90.2", period="2024")
    previous = make_slots("89.7", period="2023")

    result = check_percentage_point_difference(
        claimed, current, previous
    )

    assert "absolute, not relative" in result.assumptions[1]


def test_scale_hint_detects_power_of_ten():
    claim = make_slots("1000", decimals=0)
    evidence = make_slots("1", decimals=0)

    check = compare_slots(claim, evidence)

    assert check.result == CheckResult.MISMATCH
    hint = scale_hint(check)

    assert hint is not None
    assert "10^3" in hint


def test_scale_hint_does_not_change_match():
    claim = make_slots("91.2")
    evidence = make_slots("91.2")

    check = compare_slots(claim, evidence)

    assert check.result == CheckResult.MATCH
    assert scale_hint(check) is None


def test_pack_metadata():
    pack = ScientificResearchPack()

    assert pack.name == "scientific_research"
    assert pack.version == "0.1.0"


def test_growth_validator_is_applicable():
    pack = ScientificResearchPack()

    claim = Claim(
        claim_id=uuid4(),
        document_id=uuid4(),
        claim_text="Our accuracy improved by 5%.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id="anchor-1",
        char_start=0,
        char_end=30,
        numeric_slots=[],
        extraction_method="test",
        extraction_confidence=0.9,
    )

    validators = pack.applicable_validators(claim)

    assert "arithmetic_growth" in validators
    assert "table_to_text" in validators
    assert "unit_scale" in validators
    assert "period_condition" in validators
