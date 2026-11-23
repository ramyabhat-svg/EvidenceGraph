# Integration decisions

These Phase 0 decisions seed the platform contract. They follow the supplied Member D handoff and
the repository rules; unresolved confirmations are recorded in the request files.

1. **API contract:** prefix all API routes with `/api/v1`; use Member D's 15-endpoint list in
   `docs/reference/handoff_to_member_A.md` as the target contract.
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
9. **C-owned modules:** retrieval, NLI, and policy remain labelled stubs behind interfaces until
   Member C delivers them.
10. **Runtime:** synchronous SQLAlchemy 2.0 with psycopg 3; Python 3.11 in Docker and
    Python 3.10-compatible source.

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
- README specifies Python 3.13, while tracked bytecode was compiled for Python 3.10 and project
  handoffs support Python 3.10+. This phase keeps application code 3.10-compatible and containers
  on 3.11.
- `config/numeric.yaml` is referenced in README but is absent. Numeric configuration should come
  from run configuration, with `NumericConfig.approx_multiplier` defaulting to `"2"`.
- Claim extraction falls back to a blank spaCy sentencizer when `en_core_web_sm` is missing. Docker
  pins the model package; later run records should capture the active model status.
- The repository has 19 tracked `.pyc` files. Their removal from the index is a separate first
  human-run commit, as specified in the phase handoff.
