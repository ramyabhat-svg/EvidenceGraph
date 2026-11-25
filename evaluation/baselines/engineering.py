"""Translate the engineering backend's persisted verdicts for dev diagnostics."""

from uuid import UUID


def normalize_run(payload):
    """Preserve policy outputs and rank only the evidence with reranker scores."""
    run_id = str(UUID(payload["analysis_run_id"]))
    traces = []
    for item in payload["verdicts"]:
        provenance = {row["evidence_chunk_id"]: row for row in item["evidence"]}
        reranked = sorted(item["reranker_results"],
                          key=lambda row: (-row["score"], row["evidence_chunk_id"]))
        evidence = []
        for rank, row in enumerate(reranked, 1):
            evidence_id = row["evidence_chunk_id"]
            anchor = provenance[evidence_id]
            table = anchor["table_index"]
            evidence.append({
                "evidence_id": evidence_id, "retrieval_rank": rank,
                "source_anchor": {
                    "element_type": anchor["kind"], "page": anchor["page"],
                    "table_id": None if table is None else f"table-{table}",
                    **{key: anchor[key] for key in ("row", "col", "char_start", "char_end")},
                },
            })
        traces.append({
            "claim_id": str(UUID(item["claim_id"])),
            "verdict": {
                "verdict_status": item["status"], "confidence": item["confidence"],
                "policy_version": item["policy_version"], "reason": item["reason"],
            },
            "retrieved_evidence": evidence,
            "nli_results": [
                {"evidence_id": result["evidence_chunk_id"],
                 "probabilities": {label: result[f"{label}_score"]
                                   for label in ("entailment", "contradiction", "neutral")}}
                for result in item["nli_results"]
            ],
            "numeric_checks": [
                {"evidence_id": check["evidence_chunk_id"], "result": check["result"]}
                for slot in sorted(item["numeric_verifications"], key=lambda row: row["slot_index"])
                for check in slot["checks"]
            ],
        })
    return run_id, traces
