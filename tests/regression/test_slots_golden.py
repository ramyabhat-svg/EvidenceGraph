
from decimal import Decimal as D

import pytest

from worker.extraction.slots import (
    parse_numeric_slots,
    parse_all_numeric_slots,
    SlotContext,
)


CASES = [
    (
        "Model A reaches 91.2% accuracy on the test set.",
        {
            "metric": "accuracy",
            "entity": "Model A",
            "value": D("91.2"),
            "unit": "percent",
            "period": "test",
            "decimals": 1,
        },
    ),
    (
        "Accuracy improved by 3.2 percentage points.",
        {
            "metric": "accuracy",
            "value": D("3.2"),
            "unit": "percentage_point",
            "decimals": 1,
        },
    ),
    (
        "The model has 2.1M parameters.",
        {
            "value": D("2.1"),
            "scale": D(1000000),
            "decimals": 1,
        },
    ),
    (
        "We obtain 0.88 F1 under 5-fold CV.",
        {
            "metric": "f1",
            "value": D("0.88"),
            "unit": "ratio",
            "period": "5-fold cv",
            "decimals": 2,
        },
    ),
    (
        "Latency dropped to about 120 ms.",
        {
            "value": D("120"),
            "unit": "ms",
            "decimals": 0,
            "approximate": True,
        },
    ),
    (
        "As shown in Table 3 [12], results vary.",
        {},
    ),
]


FIELDS = [
    "metric",
    "entity",
    "value",
    "unit",
    "scale",
    "period",
    "comparison_basis",
    "denominator",
    "decimals",
    "approximate",
]


@pytest.mark.parametrize("text, expected", CASES)
def test_slots(text, expected):
    slot = parse_numeric_slots(text)

    for field in FIELDS:
        default = False if field == "approximate" else None
        wanted = expected.get(field, default)

        assert getattr(slot, field) == wanted, (
            f"{field}: {getattr(slot, field)!r} != {wanted!r}"
        )


def test_multiple_numeric_slots():
    text = "Accuracy was 95% and latency was 120 ms."

    slots = parse_all_numeric_slots(text)

    assert len(slots) == 2
    assert slots[0].value == D("95")
    assert slots[0].unit == "percent"
    assert slots[1].value == D("120")
    assert slots[1].unit == "ms"


def test_context_is_used_when_information_is_missing():
    context = SlotContext(
        metric="accuracy",
        entity="Proposed Model",
        period="test",
        anchor_id="sample-anchor",
    )

    slot = parse_numeric_slots("The result was 0.95.", context)

    assert slot.metric == "accuracy"
    assert slot.entity == "Proposed Model"
    assert slot.unit == "ratio"
    assert slot.period == "test"
    assert slot.source_anchor_id == "sample-anchor"


def test_standalone_year_is_not_a_numeric_value():
    slot = parse_numeric_slots("The experiment was conducted in 2024.")

    assert slot.value is None


def test_positive_and_negative_values():
    positive = parse_numeric_slots("The improvement was +3.4.")
    negative = parse_numeric_slots("The error decreased by -2.5.")

    assert positive.value == D("3.4")
    assert negative.value == D("-2.5")


def test_denominator_is_extracted():
    slot = parse_numeric_slots("The error rate was 5 per 1,000 samples.")

    assert slot.value == D("5")
    assert slot.denominator == "per 1000"
