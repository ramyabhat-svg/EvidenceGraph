"""Generate balanced, seeded controlled cases for the handoff's perturbation rules."""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from random import Random

RULES = {
    "value_beyond_tolerance": ("Contradicted", 2),
    "value_within_tolerance": ("Supported", 6),
    "unit_scale_swap": ("Contradicted", 2),
    "unit_incomparable": ("Needs Review", 3),
    "period_condition_swap": ("Needs Review", 3),
    "percent_vs_pp_swap": ("Needs Review", 3),
    "entity_swap": ("Needs Review", 3),
    "evidence_removed": ("Unsupported", 4),
    "low_quality_anchor": ("Needs Review", 1),
}


def generate(seed, per_type):
    """Yield equal counts across all nine draft types without using real annotations."""
    if per_type < 1:
        raise ValueError("Use a positive count per type.")
    rng = Random(seed)
    for kind, (verdict, rule) in RULES.items():
        for number in range(1, per_type + 1):
            value = Decimal(rng.randint(6051, 9799)) / 100
            latency = rng.randint(11, 30)
            latency_case = kind in {"unit_scale_swap", "unit_incomparable"}
            metric = "MAE" if latency_case else "accuracy"
            amount = str(latency if latency_case else value)
            unit = "ms" if latency_case else "%"
            entity = "Model A"
            period = "test"
            original = f"{entity} reports {metric} of {amount} {unit} on the {period} set."
            evidence = original
            params = {"original_value": amount, "original_unit": unit}
            perturbed = original
            if kind == "value_beyond_tolerance":
                params["perturbed_value"] = str(value + Decimal("1.00"))
                perturbed = original.replace(amount + " %", params["perturbed_value"] + " %")
            elif kind == "value_within_tolerance":
                # More precision in evidence than in the rounded claim.
                rounded = value.quantize(Decimal("1"))
                params["perturbed_value"] = str(rounded)
                perturbed = original.replace(amount + " %", str(rounded) + " %")
            elif kind in {"unit_scale_swap", "unit_incomparable", "percent_vs_pp_swap"}:
                new_unit = {
                    "unit_scale_swap": "s", "unit_incomparable": "kg",
                    "percent_vs_pp_swap": "percentage points",
                }[kind]
                params.update(perturbed_unit=new_unit, conversion_defined=kind == "unit_scale_swap")
                perturbed = original.replace(f"{amount} {unit}", f"{amount} {new_unit}")
            elif kind == "period_condition_swap":
                perturbed = original.replace("test set", "train set")
                params["perturbed_period"] = "train"
            elif kind == "entity_swap":
                params["perturbed_entity"] = "Model B"
                perturbed = original.replace(entity, params["perturbed_entity"])
            elif kind == "evidence_removed":
                evidence = None
                params["remove_evidence"] = True
            elif kind == "low_quality_anchor":
                params["low_quality"] = True
            anchor = {"page": 1, "element_type": "table_cell", "table_id": "table-1",
                      "row": number, "col": 1, "low_quality": kind == "low_quality_anchor"}
            yield {
                "synthetic_id": f"syn-{seed}-{kind}-{number:03d}", "seed": seed,
                "source_annotation_id": None, "perturbation_type": kind,
                "perturbation_params": params, "original_claim_text": original,
                "perturbed_claim_text": perturbed, "evidence_text": evidence,
                "evidence_anchor": anchor if evidence else None,
                "expected_verdict": verdict, "expected_policy_rule": rule,
                "status": "draft_controlled_case",
            }


def main():
    """Write a new draft benchmark file without replacing an earlier file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-type", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = list(generate(args.seed, args.per_type))
    with args.output.open("x", encoding="utf-8") as destination:
        for case in cases:
            destination.write(json.dumps(case, sort_keys=True) + "\n")
    print(f"Wrote {len(cases)} draft cases.")


if __name__ == "__main__":
    main()

