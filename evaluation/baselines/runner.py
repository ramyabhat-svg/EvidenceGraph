"""Align human annotations with run-scoped API trace exports."""

from collections import Counter

from evaluation.metrics.scoring import (
    VERDICTS,
    calibration,
    classification,
    document_bootstrap,
    ratio,
    risk_coverage,
)


def anchor_key(anchor):
    """Extract location identity shared between annotations and API anchors."""
    kind = anchor.get("element_type")
    names = ("page", "element_type", "table_id", "row", "col")
    if kind == "paragraph":
        names += ("char_start", "char_end")
    return tuple(anchor.get(name) for name in names)


def evaluate(annotations, traces, *, seed=42):
    """Calculate available metrics and preserve missing predictions as coverage gaps."""
    predictions = {}
    for trace in traces:
        claim = trace["claim_id"]
        if claim in predictions:
            raise ValueError(f"Duplicate prediction for claim {claim}")
        predictions[claim] = trace
    annotation_ids = set()
    matched = []
    for annotation in annotations:
        claim = annotation["claim_id"]
        if claim in annotation_ids:
            raise ValueError(f"Duplicate gold claim {claim}; use adjudicated records")
        annotation_ids.add(claim)
        if annotation["verdict"] not in VERDICTS:
            raise ValueError(f"Unknown gold verdict for {claim}")
        if claim in predictions:
            matched.append((annotation, predictions[claim]))

    pairs = []
    document_pairs = []
    retrieval = []
    numeric = []
    probability = []
    confidences = []
    rules = Counter()
    for gold, trace in matched:
        verdict = trace["verdict"]
        predicted = verdict["verdict_status"]
        if predicted not in VERDICTS:
            raise ValueError(f"Unknown predicted verdict for {gold['claim_id']}")
        pairs.append((gold["verdict"], predicted))
        document_pairs.append((gold["paper_id"], gold["verdict"], predicted))
        if verdict.get("policy_rule_fired") is not None:
            rules[str(verdict["policy_rule_fired"])] += 1
        expected = gold.get("expected_evidence_anchors") or (
            [gold["evidence_anchor"]] if gold.get("evidence_anchor") else []
        )
        evidence = sorted(
            trace.get("retrieved_evidence", []), key=lambda item: item["retrieval_rank"]
        )
        top_id = evidence[0]["evidence_id"] if evidence else None
        if expected:
            keys = {anchor_key(anchor) for anchor in expected}
            retrieval.append(
                {
                    anchor_key(item["source_anchor"]): min(
                        candidate["retrieval_rank"]
                        for candidate in evidence
                        if anchor_key(candidate["source_anchor"])
                        == anchor_key(item["source_anchor"])
                    )
                    for item in evidence
                    if anchor_key(item["source_anchor"]) in keys
                }
            )
        nli = next(
            (item for item in trace.get("nli_results", []) if item["evidence_id"] == top_id), None
        )
        if nli:
            probability.append((nli["probabilities"]["entailment"], gold["verdict"] == "Supported"))
        check = next(
            (item for item in trace.get("numeric_checks", []) if item["evidence_id"] == top_id),
            None,
        )
        if check and gold.get("expected_numeric_result"):
            numeric.append((gold["expected_numeric_result"], check["result"]))
        if verdict.get("confidence") is not None and predicted != "Needs Review":
            confidences.append((verdict["confidence"], predicted == gold["verdict"]))
    true_numeric = sum(a == b == "mismatch" for a, b in numeric)
    return {
        "gold_count": len(annotations),
        "matched_count": len(matched),
        "extraction_precision": ratio(len(matched), len(predictions)),
        "extraction_recall": ratio(len(matched), len(annotations)),
        "missing_claim_ids": sorted(annotation_ids - predictions.keys()),
        "classification": classification(pairs),
        "macro_f1_ci95": document_bootstrap(document_pairs, seed=seed),
        "retrieval_claim_count": len(retrieval),
        "retrieval": {
            f"recall_at_{k}": ratio(
                sum(any(rank <= k for rank in ranks.values()) for ranks in retrieval),
                len(retrieval),
            )
            for k in (1, 5, 10)
        },
        "numeric_mismatch": {
            "count": len(numeric),
            "precision": ratio(true_numeric, sum(b == "mismatch" for _, b in numeric)),
            "recall": ratio(true_numeric, sum(a == "mismatch" for a, _ in numeric)),
        },
        "abstention_rate": ratio(sum(b == "Needs Review" for _, b in pairs), len(pairs)),
        "risk_coverage": risk_coverage(confidences),
        "nli_entailment_calibration": calibration(probability),
        "policy_rules": dict(rules),
    }
