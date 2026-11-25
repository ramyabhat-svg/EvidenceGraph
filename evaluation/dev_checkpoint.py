"""Audit a human dev pilot against one engineering run and its policy input export."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from evaluation.baselines.runner import anchor_key
from evaluation.calibrate import policy_inputs
from evaluation.datasets.builder import read_jsonl, validate_splits
from evaluation.metrics.scoring import VERDICTS


def checkpoint(annotations, report, stages):
    """Check UUID coverage, complete policy inputs and matching physical anchors."""
    if not annotations or any(row.get("split") != "dev" for row in annotations):
        raise ValueError("Provide nonempty dev-only annotations.")
    validate_splits(annotations)
    run_id = UUID(report["analysis_run_id"])
    document_id = UUID(report["document_id"])
    verdicts = {UUID(row["claim_id"]): row for row in report["verdicts"]}
    by_claim = {UUID(row["claim_id"]): row for row in stages}
    if len(verdicts) != len(report["verdicts"]) or len(by_claim) != len(stages):
        raise ValueError("Duplicate claim IDs in the run or in policy inputs.")
    if any(row.get("split") != "dev" or UUID(row["analysis_run_id"]) != run_id for row in stages):
        raise ValueError("Policy input rows must identify this dev run.")

    results = []
    seen_claims = set()
    for annotation in annotations:
        claim_id = UUID(annotation["claim_id"])
        if claim_id in seen_claims or UUID(annotation["document_id"]) != document_id:
            raise ValueError("Provide unique claims from the run's PDF.")
        seen_claims.add(claim_id)
        if annotation["verdict"] not in VERDICTS or not annotation.get("adjudicated"):
            raise ValueError("Provide adjudicated EvidenceGraph verdicts.")
        expected = annotation.get("expected_evidence_anchors") or (
            [annotation["evidence_anchor"]] if annotation.get("evidence_anchor") else []
        )
        observed = set()
        if claim_id in verdicts:
            for anchor in verdicts[claim_id]["evidence"]:
                table = anchor["table_index"]
                observed.add(anchor_key({
                    **anchor, "element_type": anchor["kind"],
                    "table_id": None if table is None else f"table-{table}",
                }))
        if claim_id in by_claim:
            policy_inputs(by_claim[claim_id])
        results.append({
            "claim_id": str(claim_id), "verdict_found": claim_id in verdicts,
            "policy_inputs_found": claim_id in by_claim,
            "expected_anchor_count": len({anchor_key(anchor) for anchor in expected}),
            "matched_anchor_count": len({anchor_key(anchor) for anchor in expected} & observed),
        })
    return {"analysis_run_id": str(run_id), "document_id": str(document_id), "claims": results}


def main():
    """Write a dev-only coverage audit for a single run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--verdicts", required=True, type=Path)
    parser.add_argument("--policy-inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if any(path.stem.casefold() == "test" for path in
           (args.annotations, args.verdicts, args.policy_inputs)):
        parser.error("Use dev-only inputs.")
    result = checkpoint(
        list(read_jsonl(args.annotations)),
        json.loads(args.verdicts.read_text(encoding="utf-8-sig")),
        list(read_jsonl(args.policy_inputs)),
    )
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(result, destination, indent=2)
        destination.write("\n")


if __name__ == "__main__":
    main()
