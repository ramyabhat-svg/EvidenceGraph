# Requests for Member C

No C-owned interface is needed by the Phase 0 runtime skeleton. Before orchestration integration,
please confirm the following public contracts in `worker/orchestration/interfaces.py`:

- Retrieval input fields, candidate output fields, ranking score types, and version metadata.
- NLI input/output fields, frozen label values, confidence representation, model/version metadata,
  and controlled failure behavior.
- Decision-policy inputs, verdict output, abstention reason, policy version, and configurable
  thresholds.
- Which component results must be persisted before policy evaluation and how stubs are labelled.
- **Dense retrieval decision (approved):** use
  `sentence-transformers/all-MiniLM-L6-v2`, Apache 2.0, at revision
  `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with local CPU inference, 384-dimensional vectors,
  PostgreSQL pgvector, and cosine distance. A's orchestration adapter implements the persisted
  dense retrieval path without changing Member C's ownership area.

For the controlled pipeline audit, please also confirm or address these retrieval and model
contracts:

- BM25, dense cosine similarity, reciprocal-rank-fusion, and reranker score meanings and sorting
  directions. In particular, confirm that only the reranker score is compared with `tau_ret` and
  that score thresholds require development-set calibration.
- NLI model `id2label` values and output column ordering at the pinned revision. The adapter accepts
  the three canonical label names and uses the model's explicit index mapping when present; add a
  deterministic regression against the pinned model configuration metadata.
- NLI results should remain associated with their exact evidence IDs and only evidence that meets
  the configured relevance gate should inform verdict generation. A high reranker score alone is
  not entailment.
- Add deterministic entailment, contradiction, and neutral examples, including claim/evidence
  direction checks and cases where overlapping numbers do not establish the full comparison.

The NLI, policy adapter, and separate local reranker provider are implemented in A-owned
orchestration. Threshold calibration remains a Person D input. No files in Member C's ownership
area were changed.
