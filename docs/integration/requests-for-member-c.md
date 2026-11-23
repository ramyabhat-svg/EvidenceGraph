# Requests for Member C

No C-owned interface is needed by the Phase 0 runtime skeleton. Before orchestration integration,
please confirm the following public contracts in `worker/orchestration/interfaces.py`:

- Retrieval input fields, candidate output fields, ranking score types, and version metadata.
- NLI input/output fields, frozen label values, confidence representation, model/version metadata,
  and controlled failure behavior.
- Decision-policy inputs, verdict output, abstention reason, policy version, and configurable
  thresholds.
- Which component results must be persisted before policy evaluation and how stubs are labelled.

No files in Member C's ownership area were changed.
