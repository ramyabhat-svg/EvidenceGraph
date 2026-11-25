# Member D status after the engineering archive

The engineering archive supplies hybrid retrieval, local NLI, reranking, and
ordered verdict rules. The archive's model adapters need their pinned model
weights and PostgreSQL with pgvector. No evidence in the archive indicates
that its four threshold settings were calibrated.

## Implemented

- The combined application now connects the six-screen React workspace to the
  engineering database. Project creation, paired upload, claim traces, human
  review and run reports are available under `/api/v1/workspace`.
- The open-data pilot includes 12 SciTab claims and six cell-anchored
  SEM-TAB-FACTS examples. Their published labels support source alignment.
  Independent project annotations and dev calibration remain outstanding.

- The six-screen handoff UI, native engineering-run inspector, evaluation CLI,
  eight proposed configurations, and a controlled PDF/CSV demo.
- The native snapshot adapter and fixture-backed dev diagnostics. Evidence rank
  in this view and scoring mode means rank by persisted reranker score.
- A corpus shortlist with article license checks, two training PDF parser
  probes, a draft annotation guide, split proposal, dev query exporter, an
  agreement command, and a 90-record synthetic draft checked with B's verifier.

## Outstanding

- D must clear companion-data licenses, finalize the corpus, supply 100–150
  human labels, arrange independent labeling of the shared 40-claim subset,
  adjudicate disagreements, and freeze the document splits. The retrieval
  queries need the resulting human dev anchors.
- D and C must review generated cases and the nine-type proposal before
  freezing the benchmark. Validate workflow-level verdicts on the integrated
  backend using the dev policy rather than treating numeric comparisons as
  end-to-end verdict checks.
- For experiment execution, expose or implement configuration switches for the
  eight configurations and persist the effective configuration and model
  revisions with every exported run. The dev policy-input export now captures extraction confidence and original
  candidate ranks. A newly processed dev document must supply the first live export.
- Run on a migrated PostgreSQL/pgvector database with the pinned local models.
  Produce calibrated thresholds from the human dev set with C. Complete dev
  experiments and freeze the selected setup. Run the sealed test once, then
  complete the results and verify the write-up's citations and numbers.

## Follow-up implementation

- Imported the exact versioned C decision policy and its result entities from
  the engineering archive for dev replay. The existing A/B workflow and the
  archive's PostgreSQL and model runtime are separate.
- Added a dev-only calibration CLI to select threshold candidates using human
  labels, captured stage inputs and a documented grid. No study thresholds
  were fitted because no human dev annotations or complete stage inputs were
  supplied.
- Replayed all 90 synthetic cases with B's verifier and decision policy v2.
  All nine types match the draft labels using controlled stage inputs. The
  removed-evidence cases simulate a completed retrieval with zero candidates.
- Documented a published-table-first corpus approach and the external sources
  reviewed. No external companion files were included.
- Added batch scoring for eight attested dev reports. The batch fixture proves
  the scorer rejects an unattested configuration and preserves the output
  directory until all eight entries pass. This does not add ablation execution
  switches to the archive runtime.
