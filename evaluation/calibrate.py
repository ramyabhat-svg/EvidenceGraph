"""Fit candidate thresholds by replaying Member C's exact policy on dev data."""

import argparse
import hashlib
import json
from collections import Counter
from itertools import product
from pathlib import Path

from domain.entities import NLIClassification, NLILabel, VerdictStatus
from domain.schemas import CheckResult
from evaluation.datasets.builder import read_jsonl, validate_splits
from evaluation.metrics.scoring import VERDICTS, classification
from worker.orchestration.decision_policy import POLICY_VERSION, DecisionThresholds, decide_verdict
from worker.verification.numeric import SlotVerification

THRESHOLDS = ("tau_ext", "tau_ret", "tau_e", "tau_c")


def policy_inputs(row):
    """Decode per-claim stage outputs needed by the ordered decision policy."""
    return {
        "extraction_confidence": row["extraction_confidence"],
        "claim_low_quality": row["claim_low_quality"],
        "evidence_low_quality": row["evidence_low_quality"],
        "best_reranker_score": row["best_reranker_score"],
        "retrieval_empty": row.get("retrieval_empty", False),
        "numeric_results": [
            SlotVerification(index, CheckResult(status), "persisted", [])
            for index, status in zip(
                row.get("numeric_slot_indices", range(len(row["numeric_slot_results"]))),
                row["numeric_slot_results"], strict=True,
            )
        ],
        "nli_results": [
            NLIClassification(
                label=NLILabel(result["label"]),
                contradiction_score=result["contradiction_score"],
                entailment_score=result["entailment_score"],
                neutral_score=result["neutral_score"],
            )
            for result in row["nli_results"]
        ],
        "part_outcomes": [VerdictStatus(status) for status in row.get("part_outcomes", [])],
    }


def fit(annotations, inputs, grid):
    """Select by dev macro F1, then coverage, then the lowest threshold tuple."""
    if not annotations or any(row["split"] != "dev" for row in annotations):
        raise ValueError("Threshold calibration requires a nonempty dev-only annotation file.")
    validate_splits(annotations)
    gold = {row["claim_id"]: row["verdict"] for row in annotations}
    if len(gold) != len(annotations) or any(label not in VERDICTS for label in gold.values()):
        raise ValueError("Use one adjudicated record per claim with a known verdict.")
    raw_inputs = {row["claim_id"]: row for row in inputs}
    if len(raw_inputs) != len(inputs) or not gold.keys() <= raw_inputs.keys():
        raise ValueError("Calibration inputs must be unique and cover all annotated claims.")
    if set(grid) != set(THRESHOLDS) or any(not grid[name] for name in THRESHOLDS):
        raise ValueError("Specify candidate values for all four thresholds.")
    candidates = [sorted(set(grid[name])) for name in THRESHOLDS]
    if any(any(type(value) not in (float, int) or not 0 <= value <= 1 for value in values)
           for values in candidates):
        raise ValueError("Threshold candidates must be numbers between zero and one.")

    stage_inputs = [(gold[claim_id], policy_inputs(raw_inputs[claim_id]))
                    for claim_id in sorted(gold)]
    best = None
    tested = 0
    for values in product(*candidates):
        tested += 1
        selected = dict(zip(THRESHOLDS, values))
        thresholds = DecisionThresholds(**selected)
        predicted = [decide_verdict(thresholds=thresholds, **row).status.value
                     for _, row in stage_inputs]
        pairs = list(zip((label for label, _ in stage_inputs), predicted))
        scores = classification(pairs)
        coverage = 1 - predicted.count("Needs Review") / len(predicted)
        key = (scores["macro_f1"], coverage)
        if best is None or key > best[0]:
            best = (key, selected, scores, dict(Counter(predicted)))
    key, selected, scores, counts = best
    return {
        "policy_version": POLICY_VERSION,
        "status": "dev_candidate_pending_review",
        "thresholds": selected,
        "candidate_count": tested,
        "matched_claims": len(gold),
        "coverage": key[1],
        "classification": scores,
        "predicted_counts": counts,
    }


def main():
    """Read dev labels, stage snapshots and a preregistered grid, then save the candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if any(path.stem.casefold() == "test" for path in (args.annotations, args.inputs)):
        parser.error("Use dev-only inputs and annotations.")
    annotations = list(read_jsonl(args.annotations))
    inputs = list(read_jsonl(args.inputs))
    if any(row.get("split") != "dev" for row in inputs):
        parser.error("Every input must be explicitly marked as dev.")
    result = fit(annotations, inputs, json.loads(args.grid.read_text(encoding="utf-8-sig")))
    result["input_sha256"] = {
        name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
        for name in ("annotations", "inputs", "grid")
    }
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(result, destination, indent=2)
        destination.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
