"""Replay synthetic cases through Member B's verifier and Member C's ordered rules."""

import json
from collections import Counter, defaultdict

from domain.entities import NLIClassification, NLILabel
from evaluation.datasets.synthetic import generate
from worker.extraction.slots import parse_numeric_slots
from worker.orchestration.decision_policy import DecisionThresholds, decide_verdict
from worker.verification.numeric import SlotVerification, compare_slots


def replay():
    """Use controlled stage signals to expose policy differences before benchmark freeze."""
    thresholds = DecisionThresholds(tau_ext=0.5, tau_ret=0.5, tau_e=0.8, tau_c=0.8)
    counts = defaultdict(Counter)
    for case in generate(seed=42, per_type=10):
        has_evidence = case["evidence_text"] is not None
        numeric_results = []
        if has_evidence:
            check = compare_slots(parse_numeric_slots(case["perturbed_claim_text"]),
                                  parse_numeric_slots(case["evidence_text"]))
            numeric_results.append(SlotVerification(0, check.result, "controlled fixture", []))
        verdict = decide_verdict(
            extraction_confidence=1.0, claim_low_quality=False,
            evidence_low_quality=has_evidence and case["evidence_anchor"]["low_quality"],
            numeric_results=numeric_results,
            nli_results=[NLIClassification(NLILabel.ENTAILMENT, 0.01, 0.98, 0.01)]
            if has_evidence else [],
            best_reranker_score=0.9 if has_evidence else None,
            thresholds=thresholds,
            retrieval_empty=not has_evidence,
        )
        counts[case["perturbation_type"]][verdict.status.value] += 1
        if verdict.status.value != case["expected_verdict"]:
            counts[case["perturbation_type"]][f"difference:{verdict.reason}"] += 1
    return counts


if __name__ == "__main__":
    print(json.dumps(replay(), indent=2, sort_keys=True))
