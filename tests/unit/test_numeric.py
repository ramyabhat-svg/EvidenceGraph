
from decimal import Decimal

from domain.schemas import CheckResult, NumericSlots
from worker.verification.numeric import (
    NumericConfig,
    compare_slots,
    canonical,
)


def make_slot(
    value,
    unit="percent",
    decimals=1,
    metric="accuracy",
    entity="ours",
    period="test",
    approximate=False,
    scale=None,
):
    return NumericSlots(
        value=Decimal(str(value)) if value is not None else None,
        unit=unit,
        decimals=decimals,
        metric=metric,
        entity=entity,
        period=period,
        approximate=approximate,
        scale=scale,
    )


def test_exact_match():
    result = compare_slots(
        make_slot("91.2"),
        make_slot("91.2"),
    )
    assert result.result == CheckResult.MATCH


def test_different_values_mismatch():
    result = compare_slots(
        make_slot("91.2"),
        make_slot("85.4"),
    )
    assert result.result == CheckResult.MISMATCH


def test_rounding_tolerance():
    result = compare_slots(
        make_slot("91.2", decimals=1),
        make_slot("91.24", decimals=2),
    )
    assert result.result == CheckResult.MATCH


def test_difference_outside_tolerance():
    result = compare_slots(
        make_slot("91.2", decimals=1),
        make_slot("91.26", decimals=2),
    )
    assert result.result == CheckResult.MISMATCH


def test_approximate_value_uses_double_tolerance():
    result = compare_slots(
        make_slot("120", unit="ms", decimals=0, approximate=True),
        make_slot("121", unit="ms", decimals=0),
    )
    assert result.result == CheckResult.MATCH


def test_milliseconds_and_seconds_match():
    result = compare_slots(
        make_slot("120", unit="ms", decimals=0),
        make_slot("0.12", unit="s", decimals=2),
    )
    assert result.result == CheckResult.MATCH


def test_percent_and_ratio_match():
    result = compare_slots(
        make_slot("91.2", unit="percent"),
        make_slot("0.912", unit="ratio", decimals=3),
    )
    assert result.result == CheckResult.MATCH


def test_percentage_point_and_percent_incomparable():
    result = compare_slots(
        make_slot("3.2", unit="percentage_point"),
        make_slot("3.2", unit="percent"),
    )
    assert result.result == CheckResult.INCOMPARABLE


def test_different_periods_incomparable():
    result = compare_slots(
        make_slot("91.2", period="test"),
        make_slot("91.2", period="train"),
    )
    assert result.result == CheckResult.INCOMPARABLE


def test_different_metrics_incomparable():
    result = compare_slots(
        make_slot("91.2", metric="accuracy"),
        make_slot("91.2", metric="f1"),
    )
    assert result.result == CheckResult.INCOMPARABLE


def test_different_entities_incomparable():
    result = compare_slots(
        make_slot("91.2", entity="ours"),
        make_slot("91.2", entity="baseline"),
    )
    assert result.result == CheckResult.INCOMPARABLE


def test_missing_value_not_applicable():
    result = compare_slots(
        make_slot(None),
        make_slot("91.2"),
    )
    assert result.result == CheckResult.NOT_APPLICABLE


def test_unknown_unit_incomparable():
    result = compare_slots(
        make_slot("10", unit="unknown_unit"),
        make_slot("10", unit="unknown_unit"),
    )
    assert result.result == CheckResult.INCOMPARABLE


def test_scale_is_applied():
    slot = make_slot(
        "2.1",
        unit=None,
        decimals=1,
        scale=Decimal("1000000"),
    )

    value, unit, precision = canonical(slot)

    assert value == Decimal("2100000.0")
    assert unit == "unitless"
    assert precision == Decimal("100000.0")


def test_metric_missing_is_incomparable():
    result = compare_slots(
        make_slot("91.2", metric=None),
        make_slot("91.2", metric=None),
    )
    assert result.result == CheckResult.INCOMPARABLE
