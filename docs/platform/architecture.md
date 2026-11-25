# Platform architecture

EvidenceGraph runs as a modular monolith with separate API and worker processes. PostgreSQL
stores application state and provenance; the pgvector image provides the vector extension needed
by later retrieval work. The React web client is owned by Member D and is not part of this phase.

## Services

- **api** serves the FastAPI application under `/api/v1`, provides the `/health` alias used by
  local tooling, stores PDF/CSV uploads on the shared persistent volume, queues document rows, and
  exposes processing status and persisted analysis verdicts.
- **worker** is a separate process. It claims queued document rows, ingests their PDF or CSV
  contents, persists source locations and evidence chunks, and extracts document claims from the
  persisted evidence. For each persisted claim it retrieves project evidence while excluding the
  claim's source anchor, runs B's numeric verifier and local CPU NLI, applies the ordered policy,
  and persists run-scoped component outputs, verdicts, and provenance. Uncalibrated policy
  thresholds produce Needs Review. It exits cleanly on SIGTERM or SIGINT.
- **postgres** runs PostgreSQL 16 with pgvector and is published only on the local loopback
  interface.
- **web** is the future React/Vite client owned by Member D.

The MVP has no user authentication. The Compose stack is for local development and is not
production-safe as deployed.

## Data flow

The pipeline is upload and file validation, PDF/CSV ingestion with source anchors, claim extraction,
evidence retrieval, semantic and numeric verification, verdict generation, provenance persistence,
and report delivery. The worker implements PDF/CSV ingestion, source and evidence persistence,
claim extraction, hybrid BM25/pgvector retrieval with rank fusion, and retrieval-backed numeric
verification. A pinned local CPU NLI cross-encoder scores retrieved claim-evidence pairs, and a
separate pinned local CPU cross-encoder reranks each claim-evidence pair. The versioned decision
policy combines those outputs with persisted numeric results and writes verdict provenance. Its
calibration thresholds remain unset until Person D supplies development data and calibration
results. RRF scores are never used as reranker scores. Numeric outputs retain Decimal values and
link to persisted source chunks. The pinned local CPU embedding service generates vectors during
ingestion. The worker's transaction makes a failed analysis retryable without partial result rows;
the deterministic run identity and immutable repositories make completed retries idempotent.
Repositories expose run-scoped verdicts with evidence-chunk provenance for read-back. Existing
completed documents can be backfilled with
`python scripts/backfill_embeddings.py`.

Uploaded files use a named volume mounted at the same storage path in the API and worker
containers. Intake writes each upload to a temporary sibling and atomically renames it to a
UUID-based final path before committing its queued row. API requests do not parse documents or run
models. The database volume is separate. Both volumes are local Compose state.

## Ownership

Member A owns common platform utilities, API and persistence scaffolding, worker orchestration and
reporting, deployment, CI, and integration documentation. Member B owns ingestion, extraction,
numeric verification, and the scientific pack. Member C owns retrieval, NLI, and decision policy.
Member D owns evaluation and the web client. Cross-owner changes are recorded in
`docs/integration/requests-for-member-*.md` and implemented through A-owned adapters where
possible.
