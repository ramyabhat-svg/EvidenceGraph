# Requests for Member B

These integration requests keep Member A's changes inside A-owned directories.

1. **Add a document dispatcher.** The handoff documents `ingest_document(...) -> IngestionResult`,
   but the repository currently exposes only `ingest_pdf` and `ingest_csv`. Please add a dispatcher
   matching the handoff, or confirm that A should maintain an orchestration adapter.
2. **Align the Python version statement.** README says Python 3.13, while the handoff says 3.10+
   and tracked bytecode is compiled for 3.10. Please state the supported interpreter range and
   remove version-specific wording that conflicts with it.
3. **Resolve the missing numeric configuration file.** README references `config/numeric.yaml`,
   but it is absent. The code exposes `NumericConfig.approx_multiplier`; please confirm that A
   supplies it from run configuration and whether a versioned config file is planned.
4. **Untrack compiled bytecode.** `git ls-files "*.pyc"` lists 19 files. Please remove these from
   version control and retain the existing ignore rules.
5. **Confirm identifier integration.** B's claim IDs depend on file hash, anchor, offsets, and
   extractor version, not document ID. Identical files in distinct documents therefore share IDs.
   Please confirm A's document-scoped UUIDs as the persistence primary key and retain B's UUID as
   `extractor_claim_id`.
6. **Align the numeric verification parameter name.** The handoff names the optional argument
   `cfg`; the implementation names it `config`. Please align the handoff or implementation in a
   future B-owned change. A will pass the value positionally for compatibility.
