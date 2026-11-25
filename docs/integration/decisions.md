# Integration decisions

These Phase 0 decisions seed the platform contract. They follow the supplied Member D handoff and
the repository rules; unresolved confirmations are recorded in the request files.

1. **API contract:** prefix application routes with `/api/v1`. The minimal document intake, status,
   and analysis-run verdict contracts are defined in `docs/api.md`. The referenced Member D
   handoff is not present in this checkout; align additional frontend-facing routes with Member D
   before adding them.
2. **Document rows:** one row represents one file. An API document is a PDF and at most one
   companion CSV. The CSV row points to the PDF row with additive `parent_document_id`; the API
   document ID is the PDF row ID. There is one analysis run per API document.
3. **Enqueueing:** successful upload automatically enqueues analysis. The analyze endpoint is a
   manual re-trigger.
4. **Identifiers:** database identifiers are UUIDs and API identifiers are UUID strings.
5. **Claim and run scope:** claims are document-scoped and stable across runs using
   `derive_uuid(document_id, source_anchor_id, char_start, char_end)`. Verdicts, checks, retrieval,
   and NLI results are run-scoped. Claim numeric slots are JSONB. Ground truth uses a separate
   `annotations` table.
6. **Verdicts and review:** enum strings remain frozen as specified in `AGENTS.md`. Review events
   append to history, write a `CLAIM_REVIEWED_BY` edge, and never overwrite verdict rows.
7. **Errors and settings:** all non-422 errors use the shared error object; setting names and CORS
   follow the handoff. Stub endpoints return fixtures in the final response shape. Evaluation mode
   disables throttling; no throttling exists in Phase 0.
8. **Limits:** PDF 50 MB and 200 pages; CSV 5 MB; one CSV per document. A repeated PDF hash in a
   project returns `409 duplicate_document`.
9. **C-owned modules:** Member C's retrieval, NLI, and policy modules remain untouched. A-owned
   orchestration provides the integration adapter and persistence contracts for this phase.
10. **Runtime:** synchronous SQLAlchemy 2.0 with psycopg 3; Python 3.11 in Docker and
    Python 3.10-compatible source.
11. **Persistence foundation:** projects and documents use UUID primary keys; documents own
    filename, hash, storage path, type, status, and processing error. PDF duplicate hashes are
    unique within a project; companion CSV rows reference their parent PDF. Analysis runs are
    immutable and each rerun receives a new UUID. Source locations are normalized, evidence rows
    preserve B's chunk UUID in `source_chunk_id`, and claims use the approved document-scoped UUID
    formula while retaining B's UUID in `extractor_claim_id`. Claim numeric slots and exact
    verification slot payloads use JSONB with Decimal values encoded as strings; numeric
    tolerances and differences use unbounded `NUMERIC`. Verification results are run-scoped;
    numeric checks reference individual evidence chunks, while `verification_evidence` links
    aggregate scientific-pack results to the evidence supplied to that validator. Evidence
    `ordinal` preserves ingestion order; `result_key` and numeric-check `check_index` preserve
    result identity and per-evidence ordering for idempotent retries. Evidence and source-location
    persistence UUIDs are derived from the document UUID and the corresponding B source ID using
    `derive_uuid`. Repository methods flush but leave transaction commit/rollback to their caller.
12. **Ingestion work items:** queued document rows are claimed directly by the worker with
    `FOR UPDATE SKIP LOCKED`; no separate job table is introduced for the ingestion milestone.
    Parser and persistence failures are persisted as document processing errors, while parser
    source IDs and anchor values remain unchanged in their dedicated source fields.
13. **Claim extraction:** the worker reloads each document's persisted evidence chunks and passes
    them with the stored file hash to Member B's extractor. Claims use the document-scoped UUID
    formula already recorded above, retain B's extractor claim ID, and point to the same normalized
    source location as their source evidence chunk.
14. **Retrieval:** the A-owned orchestration adapter provides configurable BM25 and pgvector cosine
    retrieval over persisted project evidence, fused with reciprocal rank. Dense vectors use the
    approved `sentence-transformers/all-MiniLM-L6-v2` Apache-2.0 model at pinned revision
    `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, CPU-only, with 384 dimensions. Vectors record model
    identity and revision for safe retries and backfills.
15. **Retrieval corpus:** project retrieval uses evidence from completed documents only and excludes
    the claim's own source anchor when called through the verification-facing claim interface.
16. **Embedding backfill:** chunks remain queryable via BM25 when their embedding is null or stale.
    `scripts/backfill_embeddings.py` safely fills missing vectors in configured batches; retries
    with the same model revision leave already persisted vectors unchanged.
17. **NLI and decision policy:** use `cross-encoder/nli-MiniLM2-L6-H768` at revision
    `b95119ce93d3e065de6214e38cd4a97b0f2f2c6d`, Apache 2.0, with local CPU inference. Persist
    each claim-evidence score distribution and final verdict in separate run-scoped records.
    Numeric mismatch takes precedence over incomparable numeric slots; otherwise any required
    incomparable slot abstains. The configurable `POLICY_TAU_EXT`, `POLICY_TAU_RET`,
    `POLICY_TAU_E`, and `POLICY_TAU_C` remain unset pending Person D's development-set
    calibration. No RRF value substitutes for a reranker score.
18. **Reranker:** use `cross-encoder/ms-marco-MiniLM-L6-v2` at revision
    `233902d25c440f23af6f7d6e94d2946bac0bee0a`, Apache 2.0, with local CPU inference. The
    provider converts the model's raw relevance logit with sigmoid to a monotonic score in `[0,1]`;
    this is a ranking score, not a calibrated probability. `POLICY_TAU_RET` remains unset pending
    Person D's development-set calibration. The provider preserves retrieval evidence order and
    does not alter BM25, dense retrieval, or RRF.
19. **Upload storage:** intake uses the existing `STORAGE_ROOT` and shared Compose named volume.
    Files are atomically renamed from a temporary sibling to a UUID-based durable path before the
    queued document transaction commits. CSV uploads require a same-project parent PDF, following
    the existing document repository relationship contract. The one-companion-CSV rule is enforced
    with a partial unique index so concurrent uploads cannot violate it.

## Phase 0 findings

- Member B currently has separate `ingest_pdf` and `ingest_csv` functions and no
  `ingest_document` dispatcher. A later orchestration adapter will dispatch without editing B's
  code.
- Member B's `verify_numeric_claim` parameter is named `config`, while the handoff says `cfg`.
  Callers must pass the optional configuration positionally until the contract is aligned.
- Member B's deterministic claim UUID includes file hash, anchor, offsets, and extractor version,
  but not document ID. Identical source files in separate documents can therefore share B's ID;
  A must derive document-scoped claim IDs for persistence.
- Decimal values in numeric slots and checks require lossless string serialization and unconstrained
  database numeric types when persistence is introduced.
- The scientific pack calls numeric verification internally. Orchestration should persist that
  output separately from the direct numeric verification result.
- Numeric verification is run for each persisted claim using hybrid retrieval results, excluding
  the claim's own document and source anchor. The orchestration persists a stable run identity
  derived from the document and effective retrieval/numeric configuration, so exact retries reuse
  the same result and numeric-check rows. Evidence links point to platform chunk IDs while the
  stored checks retain B's source chunk IDs and Decimal values.
- README specifies Python 3.13, while tracked bytecode was compiled for Python 3.10 and project
  handoffs support Python 3.10+. This phase keeps application code 3.10-compatible and containers
  on 3.11.
- `config/numeric.yaml` is referenced in README but is absent. Numeric configuration should come
  from run configuration, with `NumericConfig.approx_multiplier` defaulting to `"2"`.
- Claim extraction falls back to a blank spaCy sentencizer when `en_core_web_sm` is missing. Docker
  pins the model package; later run records should capture the active model status.
- The repository has 19 tracked `.pyc` files. Their removal from the index is a separate first
  human-run commit, as specified in the phase handoff.

## Engineering review workspace

Migration 0006 adds optional project names, descriptions, upload titles and submission timestamps.
Historical uploads keep their filename and historical projects can be selected by UUID.
Human review events reference the immutable engineering verdict and have independent reviewer,
rationale and timestamp fields. A paired PDF waits for its CSV ingestion transaction to finish
so ranked evidence can include companion rows.
