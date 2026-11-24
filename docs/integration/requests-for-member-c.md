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

The NLI, policy adapter, and separate local reranker provider are implemented in A-owned
orchestration. Threshold calibration remains a Person D input. No files in Member C's ownership
area were changed.
