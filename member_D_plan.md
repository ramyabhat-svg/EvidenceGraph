# Member D: Work Plan
## Evaluation, Data, and UI Lead — EvidenceGraph

**Directories you own:** `evaluation/`, `apps/web/`, `docs/`  
**Files you co-own at the project root:** `DEMO.md`, your section of `README.md`, license inventory entries for evaluation datasets  
**Cross-review rotation:** D reviews A's PRs. (A→B, B→C, C→D, D→A)

---

## 0. Non-Negotiable Rules

Before anything else, internalize these. Violating them compromises the research validity of the whole project.

1. **No AI ground truth.** Never use an AI model to assign a verdict label. All annotations are human-produced. AI may suggest text; you verify and decide.
2. **The test set is sealed.** Do not open `evaluation/datasets/splits/test.jsonl` until Week 10. Do not run the pipeline against it during development. The split files live in version control but the test set is access-controlled by convention — document this in `evaluation/datasets/splits.md`.
3. **One test run.** Run the sealed test split exactly once with the frozen policy version. Record every result honestly, including negative ones.
4. **Every citation is opened.** If an AI suggests a paper, you open the PDF and read it before adding it to the related-work section. Never cite from an abstract alone.
5. **Every number traces to a command.** Every metric in the write-up must be producible by running `python evaluation/run_eval.py --experiment <name> --split <split>`. No manually typed numbers.
6. **Thresholds are C's, not yours.** Thresholds (τ_ext, τ_ret, τ_e, τ_c) are set by Member C on the dev set. You record and report them. You do not set them.
7. **`domain/schemas.py` and `domain/policies.py` are read-only for you.** Raise changes in the weekly sync.

---

## 1. Repository Skeleton You Create

Create these directories and placeholder `__init__.py` or `.gitkeep` files in Week 1–2. The AI can generate the skeleton once you've agreed on the structure.

**Two-stage frontend setup — important:**
- **Weeks 1–2:** Create `apps/web/` with a minimal placeholder `package.json` and `.gitkeep` files to reserve the structure. Do not initialise Vite or install dependencies yet.
- **Week 6:** Replace the placeholder with the full `vite create` scaffold, install dependencies, and begin building components. This is when `package.json` gets its real content and `tsconfig.json` is created.

```
evaluation/
├── datasets/
│   ├── corpus_index.md          # paper list with licenses and splits
│   ├── splits.md                # frozen split documentation
│   ├── splits/
│   │   ├── train.jsonl          # annotated records, train split
│   │   ├── dev.jsonl            # annotated records, dev split
│   │   └── test.jsonl           # SEALED until Week 10
│   ├── synthetic.py             # perturbation generator
│   ├── synthetic_benchmark.jsonl # frozen generated benchmark
│   └── builder.py               # assembles synthetic + real into eval sets
├── annotations/
│   ├── guidelines_v1.md         # annotation guidelines
│   ├── claims_annotated.jsonl   # all annotated real claims
│   └── disagreements.md        # inter-annotator disagreements and resolutions
├── baselines/
│   ├── configs/
│   │   ├── baseline_bm25_nli.json
│   │   ├── baseline_hybrid_nli.json
│   │   ├── baseline_hybrid_rerank_nli.json
│   │   ├── full_system.json
│   │   ├── ablation_no_dense.json
│   │   ├── ablation_no_reranker.json
│   │   ├── ablation_no_table_context.json
│   │   └── ablation_no_abstention.json
│   └── runner.py                # iterates configs, calls pipeline, collects predictions
├── metrics/
│   ├── classification.py        # per-class P/R/F1, macro-F1, confusion matrix
│   ├── numeric_verification.py  # mismatch detection P/R
│   ├── retrieval.py             # Recall@k, source-anchor accuracy
│   ├── abstention.py            # abstention rate, risk-coverage curve
│   ├── calibration.py           # Brier score, ECE
│   ├── agreement.py             # Cohen's kappa, Krippendorff's alpha
│   └── bootstrap.py             # CI computation resampled by document
├── adapters/
│   ├── scifact.py               # loader for SciFact format → internal format
│   ├── scitab.py
│   └── tatqa.py
├── results/                     # gitignored or tracked separately
│   └── .gitkeep
├── import_annotations.py        # upserts annotated records into evaluation DB
└── run_eval.py                  # main CLI entry point

apps/web/
├── src/
│   ├── api/
│   │   ├── client.ts
│   │   ├── projects.ts
│   │   ├── documents.ts
│   │   ├── claims.ts
│   │   └── runs.ts
│   ├── components/
│   │   ├── Upload/
│   │   │   ├── UploadPage.tsx
│   │   │   └── UploadPage.test.tsx
│   │   ├── Documents/
│   │   │   ├── DocumentList.tsx
│   │   │   └── DocumentList.test.tsx
│   │   ├── Claims/
│   │   │   ├── ClaimList.tsx
│   │   │   ├── ClaimList.test.tsx
│   │   │   ├── ClaimDetail.tsx
│   │   │   └── ClaimDetail.test.tsx
│   │   ├── Review/
│   │   │   ├── ReviewForm.tsx
│   │   │   └── ReviewForm.test.tsx
│   │   └── Runs/
│   │       ├── RunHistory.tsx
│   │       └── RunHistory.test.tsx
│   ├── types/
│   │   └── api.ts
│   ├── App.tsx
│   └── main.tsx
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json                # strict: true
└── package.json

docs/
├── perturbations.md             # perturbation spec (you write, AI does not)
├── related_work.md
└── write_up_draft.md
```

---

## 2. Week-by-Week Plan

### Week 1 — Contracts and Setup

**Human work (you, non-delegatable):**

- [ ] **Contracts meeting.** Participate in writing `domain/schemas.py`. Your specific inputs:
  - `ClaimType` enum: agree the exact strings (`quantitative | comparative | temporal | citation | categorical | other`)
  - `VerdictStatus` enum: agree the exact strings and confirm `Processing Error` is document-level only, not a claim verdict
  - `NumericSlots` Pydantic model: confirm all 10 fields, agree that `value` is `Decimal`-derived `str` not `float`
  - `SourceAnchor` Pydantic model: confirm it stores `page`, `element_type`, `char_start`, `char_end`, `table_id`, `row`, `col`, `bounding_box`
  - `claim_id` hash formula: agree it with A and document it in `domain/schemas.py`

- [ ] **Literature search.** Start searching for related work. Minimum papers to have in your reading queue by end of Week 1:
  - SciFact (Wadden et al., 2020)
  - SciTab (Lu et al., 2023)
  - FEVEROUS (Aly et al., 2021)
  - TAT-QA (Zhu et al., 2021)
  - NumericNLI (Ravichander et al., 2019)
  - FinQA (Chen et al., 2021)
  - At least 3 papers on numeric fact-checking or claim verification
  - Open and read each one — do not cite from abstract.

- [ ] **Paper shortlist.** Start listing candidate papers for the real annotation corpus. Criteria:
  - Open license (CC-BY, CC0, arXiv preprints are generally fine — verify each)
  - English, scientific domain
  - Has result tables with numeric metrics
  - Has accompanying CSVs or clearly extractable tabular data
  - At least 8 papers total; aim for 12 to have margin

- [ ] **Review `AGENTS.md`** once A drafts it. Flag anything that affects annotation or evaluation tooling.

**AI can do:**
- Generate the directory skeleton with `.gitkeep` files
- Suggest literature search queries (you verify every result)

**Week 1 gate:**
- `domain/schemas.py` frozen as v0, committed
- `claim_id` hash formula documented in `domain/schemas.py`
- Compose skeleton starts from a clean clone
- Your paper shortlist has ≥ 8 entries with license notes

---

### Week 2 — Data Foundations

**Human work:**

- [ ] **Finalize corpus.** Lock 8–15 papers. For each, record in `evaluation/datasets/corpus_index.md`:

  ```markdown
  | paper_id   | title                    | DOI / URL          | license | has_csv | est_claims | split |
  |------------|--------------------------|--------------------|---------|---------|-----------:|-------|
  | paper-001  | Example Paper Title      | https://arxiv.org/ | CC-BY   | yes     |         20 | train |
  ```

  Split is by document — no paper in more than one split. Suggested ratio: 50% train, 25% dev, 25% test. Dev and test should have at least 3 papers each.

- [ ] **Write annotation guidelines v1.** File: `evaluation/annotations/guidelines_v1.md`. Must cover:
  - How to identify a claim span (include/exclude hedging language, sentence boundary rules)
  - What counts as a numeric claim vs. a non-checkable claim
  - How to fill each slot: `metric`, `entity`, `value`, `unit`, `scale`, `period`, `comparison_basis`, `denominator`, `precision`, `rounding` — with worked examples for each
  - How to assign each `VerdictStatus` — with examples for each status and decision-tree for ambiguous cases
  - How to record a `source_anchor` (page, element type, table cell coordinates)
  - When to use `Needs Review` vs. `Unsupported`
  - Minimum 4 pages with worked examples from real papers

- [ ] **Begin annotating train split.** Use the annotated record schema (see §7). Target ≥10 claims annotated by end of Week 2.

**AI can do:**
- Draft a first version of the annotation guidelines — you rewrite every section
- Create the directory scaffold and template files

**Week 2 gate:**
- `evaluation/datasets/corpus_index.md` committed with all papers
- `evaluation/annotations/guidelines_v1.md` committed
- Train-split annotation started
- Uploading a PDF and CSV produces anchored chunks in the DB (A's gate — you verify it works with your test paper)

---

### Week 3 — Perturbation Spec and Generator v0

**Human work:**

- [ ] **Write `docs/perturbations.md`.** This is the spec the AI implements from. It must be complete before you prompt the AI for the generator. Include for each perturbation type:
  - Exact name (used as the `perturbation_type` string in the benchmark)
  - Description of what is changed
  - Expected verdict and the policy rule it should fire (reference Framework §4.8)
  - Example: before and after claim text, before and after evidence text

  Required perturbation types:

  | `perturbation_type` | What changes | Expected verdict | Policy rule | Condition for this label |
  |---|---|---|---|---|
  | `value_beyond_tolerance` | Claim value changed > tolerance, same metric/entity/period/unit | Contradicted | Rule 2 | All slots comparable; value outside tolerance |
  | `value_within_tolerance` | Claim value rounded within tolerance (e.g., 91.2 → 91%) | Supported | Rule 6 | All slots comparable; value inside tolerance |
  | `unit_scale_swap` | Unit changed to a **mathematically convertible** unit with a known factor (e.g., g → mg, km → m) — the converted value no longer matches | Contradicted | Rule 2 | Conversion is unambiguous (Pint-resolvable); value after conversion is outside tolerance |
  | `unit_incomparable` | Unit changed to an **incomparable** unit (e.g., % → percentage points, where no agreed conversion exists in evidence) | Needs Review | Rule 3 | Units are not comparable; result is `incomparable` |
  | `period_condition_swap` | Period/condition changed to a value present in the same document (e.g., test set → train set) | Needs Review | Rule 3 | Different period means slots are not comparable |
  | `percent_vs_pp_swap` | "%" swapped for "percentage points" — these are always incomparable without explicit denominator | Needs Review | Rule 3 | Incomparable units; result is `incomparable` |
  | `entity_swap` | Entity changed to a different entity that also appears in evidence (e.g., Model A → Model B) | Needs Review | Rule 3 | Claim entity does not match evidence entity; slots incomparable |
  | `evidence_removed` | Evidence for the claim removed from the evidence set | Unsupported | Rule 4 | No evidence retrieved above τ_ret |
  | `low_quality_anchor` | Table structure artificially degraded or anchor flagged `low_quality` | Needs Review | Rule 1 | Extraction quality below τ_ext |

  **Important:** Perturbations that change the entity, period, or unit to something the numeric validator cannot compare result in `incomparable`, not `mismatch`, per Framework §4.6 Rule 3. Only `value_beyond_tolerance` and `unit_scale_swap` (with a known conversion) produce `Contradicted`. This is a deliberate design decision — do not change these labels without a team decision and a policy update.

- [ ] **Define the synthetic record schema** (agree this is what you write in the spec doc, not left to the AI):

  ```json
  {
    "synthetic_id": "syn-0042",
    "source_annotation_id": "ann-001",
    "perturbation_type": "unit_scale_swap",
    "perturbation_params": {
      "original_unit": "%",
      "perturbed_unit": "percentage_points",
      "conversion_defined": false
    },
    "perturbed_claim_text": "Model A achieves 91.2 percentage points accuracy on the test set.",
    "original_claim_text": "Model A achieves 91.2% accuracy on the test set.",
    "expected_verdict": "Needs Review",
    "expected_policy_rule": 3,
    "evidence_text": "Model A: 91.2% accuracy (test set)",
    "evidence_anchor": {
      "page": 5,
      "element_type": "table_cell",
      "table_id": "table-3",
      "row": 2,
      "col": 3
    },
    "seed": 42
  }
  ```

- [ ] **Review generator v0.** After the AI implements `evaluation/datasets/synthetic.py`, run it and verify manually for at least 10 examples per perturbation type. Check: is the label correct? Does the perturbed text look realistic? Are the slots what the numeric validator will parse?

- [ ] **Continue annotating.** Dev split priority. Target ≥ 30 total claims annotated.

**AI can do:**
- Implement `evaluation/datasets/synthetic.py` from your spec — tests must pass before you accept the PR
- Write unit tests for the generator (same seed → identical output; all types represented)

**Week 3 gate:**
- `docs/perturbations.md` committed
- Generator v0 producing outputs; you have hand-verified ≥ 10 per type
- Extraction P/R reported by B on dev set — you record the numbers

---

### Week 4 — Retrieval Metrics and Annotation Progress

**Human work:**

- [ ] **Continue dev split annotation.** Target: 50–75 total claims by end of week. Focus on claims that involve tables (these are the hard cases for retrieval).

- [ ] **Prepare retrieval evaluation queries.** From your annotated dev claims, produce a file `evaluation/datasets/retrieval_eval.jsonl` — one record per claim with `claim_id`, `claim_text`, and `expected_evidence_anchor`. Hand to C so they can measure Recall@k.

  ```json
  {
    "claim_id": "clm-001",
    "claim_text": "Model A achieves 91.2% accuracy on the test set.",
    "expected_evidence_anchors": [
      { "page": 5, "element_type": "table_cell", "table_id": "table-3", "row": 2, "col": 3 }
    ]
  }
  ```

- [ ] **Plan inter-annotator agreement.** Pick the second annotator (A, B, or C — coordinate at the weekly sync). Select a 40-claim shared subset from your dev annotations. The subset should include a mix of all verdict types and at least 10 `Needs Review` cases (the hard ones). Schedule the second annotator to label them independently in Week 5.

- [ ] **Read 3–5 related-work papers.** Take notes in `docs/related_work.md` (even rough notes). Record: paper ID, key contribution, how it relates to EvidenceGraph, any result numbers you might cite.

**AI can do:**
- Write adapter scripts for SciFact, SciTab, TAT-QA (you decide which to run after license check)
- Error-analysis scripts (confusion matrices on dev predictions once the pipeline is running)

**Week 4 gate:**
- Recall@5 reported by C — you record it in your eval log
- Dev split annotation ≥ 50 claims
- Shared 40-claim subset identified and second annotator scheduled

---

### Week 5 — Synthetic Benchmark v1 and Inter-Annotator Agreement

**Human work:**

- [ ] **Run inter-annotator agreement.** Second annotator independently labels the 40-claim shared subset. Compute Cohen's kappa using `evaluation/metrics/agreement.py`.
  - If κ ≥ 0.7: proceed
  - If κ < 0.7: schedule a 1-hour calibration session, revise guidelines, re-label the subset, recompute
  - Record the final κ value and disagreement details in `evaluation/annotations/disagreements.md`

  Format for `disagreements.md`:
  ```markdown
  ## ann-047
  - Annotator 1: Supported
  - Annotator 2: Needs Review
  - Resolution: Needs Review (evidence anchor was low-quality table; Rule 1 applies)
  - Agreed verdict: Needs Review
  ```

- [ ] **Adjudicate all disagreements.** Go through every disagreement with the second annotator. Reach a final verdict for each. Update `claims_annotated.jsonl` with adjudicated labels. Mark adjudicated records with `adjudicated: true`.

- [ ] **Freeze splits.** Write `evaluation/datasets/splits.md`:
  - How many papers per split
  - How many claims per split (after annotation)
  - Which paper IDs are in each split
  - Confirm no paper appears in two splits

- [ ] **Finalize and freeze the synthetic generator.** Freeze the master seed. Run the full generator and commit `evaluation/datasets/synthetic_benchmark.jsonl`. Verify:
  - All 8 perturbation types represented
  - Balanced counts per type (within ±10%)
  - Same seed produces identical output on a fresh run

**AI can do:**
- Implement `evaluation/datasets/builder.py` that assembles train/dev sets from annotated + synthetic records
- Agreement computation in `evaluation/metrics/agreement.py` (you check the formula against a 3×3 hand-calculated example)

**Week 5 gate:**
- Inter-annotator κ ≥ 0.7 (or documented reason for lower)
- `evaluation/datasets/splits.md` committed
- `evaluation/datasets/synthetic_benchmark.jsonl` committed and frozen
- Total annotated claims: 100–150

---

### Week 6 — UI Scaffold and E2E Milestone

**Human work:**

- [ ] **Sketch all 6 UI screens** before writing a single line of React. Use paper, whiteboard, Excalidraw — anything. The sketches are what you hand to the AI. Required screens:

  **Screen 1: Upload Page**
  - Inputs: project name (text), PDF file picker (`.pdf` only), CSV file picker (`.csv`, optional)
  - Submit button — disabled until project name and PDF are filled
  - Inline validation: file type error, file size error
  - On submit: POST to `/api/v1/projects` (if new project) then POST to `/api/v1/projects/{id}/documents`
  - After submit: redirect to Document List, showing the new document with status badge `Queued`

  **Screen 2: Document List (Project View)**
  - Header: project name
  - Table columns: Display name | Type (PDF/CSV) | Upload date | Status badge | Claim count
  - Status badges: `Queued` (grey), `Processing` (blue spinner), `Complete` (green), `Error` (red)
  - Polling: if any document is `queued` or `processing`, poll `GET /documents/{id}` every 5 seconds
  - Click a row → navigate to Claim List for that document
  - "Upload new document" button → Upload Page

  **Screen 3: Claim List**
  - Filter bar: status checkboxes — All | Supported | Partially Supported | Contradicted | Unsupported | Needs Review
  - Count badge per status above the table
  - Table columns: Claim text (truncated at 100 chars) | Type | Verdict badge (color-coded) | Source (page / table)
  - Verdict badge colors: Supported=green, Contradicted=red, Unsupported=yellow, Needs Review=grey, Partially Supported=blue
  - Pagination: page controls at bottom
  - Click a row → navigate to Claim Detail

  **Screen 4: Claim Detail**
  Collapsible sections (all expanded by default):
  1. **Claim** — full claim text (plain text, no HTML), source anchor (page, element type, table/cell if applicable), claim type badge, extraction confidence (e.g., "91%"), extraction method
  2. **Retrieved Evidence** — one card per evidence item, ordered by `retrieval_rank`. Each card: evidence text (plain), source anchor, rank badge, reranker score bar
  3. **Semantic Verification** — per evidence item: NLI label badge, probability bar chart (entailment/contradiction/neutral), model version footnote
  4. **Numeric Verification** — per evidence item: claim slots table, evidence slots table, result badge (match/mismatch/incomparable/not_applicable), tolerance used, trace as a numbered list of plain-text steps
  5. **Verdict** — large status badge, policy rule number (e.g., "Rule 6"), abstention reason (if any), policy version, run timestamp
  6. **Human Reviews** — chronological list of review events: timestamp, reviewer, previous verdict → new verdict, note

  **Screen 5: Review Form** (embedded at bottom of Claim Detail, below Review History)
  - Dropdown: "Override verdict to..." — options: Supported | Partially Supported | Contradicted | Unsupported | Needs Review
  - Text area: "Note (required)" — min 1 char, max 2000 chars
  - Checkbox: "Flag for re-run"
  - Submit button — disabled until note has content
  - On submit: POST to `/api/v1/claims/{id}/reviews`; on success, re-fetch claim detail and append new review to history

  **Screen 6: Run History**
  - Table columns: Run ID (short) | Document | Started | Duration | Status | Claims | Errors | Policy version
  - Click a row → expandable panel showing full run config JSON (read-only, formatted)

- [ ] **Prepare E2E scenario data.** Pick one public paper from your corpus. Manually introduce one deliberate numeric inconsistency into a copy of the paper (e.g., change "91.2%" to "87.4%" in the text but leave the table unchanged). Document in `DEMO.md`:
  - Which paper
  - What was changed and where (page, paragraph)
  - What the pipeline should produce: which claim should be `Contradicted`, which policy rule, what the numeric trace should show

- [ ] **Scope freeze.** After this week no new features. New ideas go to a `docs/future_work.md` list.

**AI can do (from your sketches):**
- Scaffold `apps/web/` with Vite + React + TypeScript + Tailwind
- Generate skeleton components with correct props interface for each screen
- Wire the API client in `src/api/`

**Week 6 gate — E2E milestone (all 8 must pass):**
1. Upload one public research PDF and one supporting CSV via the UI
2. Extraction produces 5–10 claims with numeric slots visible in the DB
3. Retrieval populates `retrieval_candidates` for each claim
4. NLI and numeric verification results stored in `verification_results` and `numeric_checks`
5. The deliberately introduced inconsistency is labeled `Contradicted` with a numeric trace
6. At least one claim is `Needs Review` with `abstention_reason` set; at least one is `Unsupported`
7. Claim detail UI shows the full trace: evidence cards, NLI scores, numeric trace, verdict, policy rule
8. Re-run with pinned config (same model revisions, same τ values) produces identical `verdict_status` for all claims

---

### Week 7 — Full UI and Evaluation Runner

**Human work:**

- [ ] **Review the full UI against your sketches.** Checklist:
  - [ ] Claim text is plain text — no HTML tags rendered
  - [ ] Evidence text is plain text — no HTML tags rendered
  - [ ] Numeric trace renders as a numbered list, not a code block
  - [ ] Source anchors show page number and, for table cells, table ID + row + col
  - [ ] Review form: submitting with an empty note is blocked by the UI
  - [ ] After submitting a review, the review appears in the history without a page reload
  - [ ] Status filter on claim list correctly shows only claims with the selected verdict
  - [ ] Pagination: navigating pages works; total count is consistent

- [ ] **End-to-end test the review flow.** Submit a review via the UI. Then open `GET /claims/{id}/reviews` in a browser or curl and confirm the review is stored with the correct `previous_verdict`.

- [ ] **Freeze the evaluation experiment matrix.** Commit the 8 config files under `evaluation/baselines/configs/`. Each config is a JSON file specifying which pipeline components are active. Example:

  ```json
  {
    "experiment_name": "baseline_bm25_nli",
    "description": "BM25 retrieval only + NLI verdict. No dense retrieval, no reranker, no numeric verification.",
    "retrieval": {
      "use_bm25": true,
      "use_dense": false,
      "use_reranker": false,
      "bm25_k": 10
    },
    "verification": {
      "use_nli": true,
      "use_numeric": false
    },
    "policy": {
      "disable_abstention": false
    }
  }
  ```

  Configs needed:
  - `baseline_bm25_nli.json`
  - `baseline_hybrid_nli.json` — adds dense retrieval
  - `baseline_hybrid_rerank_nli.json` — adds reranker
  - `full_system.json` — adds numeric verification
  - `ablation_no_dense.json`
  - `ablation_no_reranker.json`
  - `ablation_no_table_context.json`
  - `ablation_no_abstention.json` — all `Needs Review` forced to a verdict

- [ ] **Define the `run_eval.py` CLI interface.** Write the interface contract before prompting the AI to implement it:

  ```
  python evaluation/run_eval.py \
      --experiment full_system \
      --split dev \
      --config evaluation/baselines/configs/full_system.json \
      --output evaluation/results/full_system_dev_20260210.json
  ```

  Output schema: see §9.2 below.

**AI can do (from your specs):**
- Implement `evaluation/baselines/runner.py` and `evaluation/run_eval.py`
- Implement `evaluation/metrics/classification.py`, `retrieval.py`, `abstention.py`, `bootstrap.py`
- Complete remaining UI components from your review notes

**Week 7 gate:**
- Claim detail UI shows full trace including numeric trace steps
- Report exports as JSON and static HTML (verify HTML has no raw injected text)
- Evaluation runner completes one baseline run end-to-end

---

### Week 8 — Dev Set Evaluation

**Human work:**

- [ ] **Run all 8 experiments on the dev set.** Do not touch the test set. For each experiment:
  ```
  python evaluation/run_eval.py --experiment <name> --split dev --config ... --output ...
  ```

- [ ] **Produce the first results table.** Format for the write-up:

  | Configuration | Macro-F1 | Contradict P | Contradict R | Mismatch P | Mismatch R | Abstention | Recall@5 |
  |---|---|---|---|---|---|---|---|
  | BM25 + NLI | | | | | | | |
  | Hybrid + NLI | | | | | | | |
  | Hybrid + Reranker + NLI | | | | | | | |
  | Full system | | | | | | | |
  | − Dense retrieval | | | | | | | |
  | − Reranker | | | | | | | |
  | − Table context | | | | | | | |
  | − Abstention | | | | | | | |

  Numbers come from harness output files only. Do not manually type them — copy-paste from the JSON.

- [ ] **Write 2–3 paragraphs on failure modes.** Look at the confusion matrix and the claims where the full system failed. Common failure categories to look for:
  - Numeric mismatch labeled `incomparable` (which slot failed — metric, entity, period?)
  - High NLI entailment score on actually contradicted claims (NLI overconfidence on numeric claims)
  - Evidence retrieved but wrong anchor (retrieval finds the right page but wrong table cell)
  - Abstention on claims that should be decidable

- [ ] **Hand top 3 failure categories to B and C.** Document them as GitHub issues on their respective directories. They fix on dev only.

**AI can do:**
- Produce formatted tables and confusion matrix plots from results JSON
- Implement `evaluation/metrics/bootstrap.py` (you verify CI formula on a 5-claim hand-calculated example)
- Implement risk-coverage curve plots

**Week 8 gate:**
- First results tables produced from dev set with bootstrap CIs
- Top failure modes documented as GitHub issues

---

### Week 9 — Write-Up Draft and Test-Set Prep

**Human work:**

- [ ] **Write the following write-up sections** (file: `docs/write_up_draft.md`):
  - **Introduction:** motivation, research question (copy from Framework §1 but rewrite in your own words), what we show
  - **Related Work:** for each paper in your reading list, 2–4 sentences on contribution + how it differs from EvidenceGraph. Group by sub-area: claim extraction, table fact-checking, numeric verification, abstention/calibration
  - **Methods:** pipeline overview, claim schema, numeric slot formalization, decision policy (table from Framework §4.8), evaluation setup, annotation process, inter-annotator agreement
  - **Limitations:** text-based PDFs only, English only, one domain, ~100–150 real claims, CPU-only inference, no fine-tuning
  - Leave Results blank — you fill it in Week 10 from the test run

- [ ] **Prepare the held-out test run protocol.** Write `evaluation/TEST_RUN_PROTOCOL.md`:
  ```markdown
  # Test Run Protocol — EvidenceGraph

  **Date:** (fill in Week 10)
  **Policy version:** v1.0 (frozen by C in Week 9)
  **Config file:** evaluation/baselines/configs/full_system.json
  **Command:**
  python evaluation/run_eval.py --experiment full_system --split test \
      --config evaluation/baselines/configs/full_system.json \
      --output evaluation/results/full_system_test_FINAL.json

  **Pre-conditions:**
  - [ ] Policy version confirmed frozen with C
  - [ ] Model revisions pinned in config
  - [ ] Fresh clone of main branch
  - [ ] A has confirmed clean-clone reproducibility
  - [ ] This command has not been run before on the test split
  ```

- [ ] **Review C's frozen thresholds.** Read the threshold-calibration report C produces. Confirm you understand the risk-coverage trade-off they made. If you disagree with a threshold choice, raise it before the policy is frozen.

**AI can do:**
- Wording edits on write-up draft (you verify every sentence)
- Generate report skeleton from harness output files

**Week 9 gate:**
- Policy frozen by C
- Write-up draft complete (Results section blank)
- Test run protocol committed and reviewed by all four members

---

### Week 10 — Final Test Run and Write-Up

**Human work:**

- [ ] **Run the sealed test split once.** Follow `evaluation/TEST_RUN_PROTOCOL.md` exactly. Record every result. If the pipeline errors on a test document, record the error honestly — do not fix and re-run.

- [ ] **Fill in the Results section.** Numbers come from `evaluation/results/full_system_test_FINAL.json` only. No manually typed values.

- [ ] **Reproducibility check.** Run the dev set command a second time with the same seed and config. Confirm the output file is identical (use `diff` or a hash comparison). Document the hash in `TEST_RUN_PROTOCOL.md`. **Do not run the test set a second time** — the one-run rule is absolute. Reproducibility is verified on the dev set only.

- [ ] **Verify all citations** in `docs/write_up_draft.md`. For every citation: open the PDF, confirm the claim you're making about it is accurate, check the year and venue.

- [ ] **Write `DEMO.md`.** Step-by-step walkthrough:
  ```
  1. git clone <repo> && docker compose up -d
  2. Open http://localhost:5173
  3. Create project "NeurIPS Demo"
  4. Upload <paper.pdf> and <paper_tables.csv>
  5. Wait for status "Complete" (approx. 2 min)
  6. Click the document → Claim List
  7. Filter by "Contradicted" → see clm-XXX flagged
  8. Click clm-XXX → Claim Detail → show numeric trace
  9. Submit a review: override to "Needs Review", note "Table header ambiguous"
  10. Export report: GET /api/v1/runs/{id}/report?format=html
  ```

**AI can do:**
- Produce final formatted tables and figures from results JSON
- Wording edits on write-up (you verify every sentence, especially the Results section)

**Week 10 gate:**
- Test results reproducible from one command
- `docs/write_up_draft.md` complete with all citations verified and all numbers from harness
- `DEMO.md` complete
- `evaluation/TEST_RUN_PROTOCOL.md` completed with actual run date and output hash

---

## 3. Complete Task Inventory

### 3.1 Literature

| Task | Owner | Week | Notes |
|---|---|---|---|
| Search and shortlist related papers | D | 1–2 | Human only |
| Read each paper (open PDF) | D | 1–4 | Human only; AI may not summarize as a substitute |
| Draft `docs/related_work.md` notes | D | 4–9 | Human writes; AI edits wording |
| Write novelty paragraph | D | 9 | Human only |
| Final citation verification | D | 10 | Human only |

### 3.2 Corpus and Splits

| Task | Owner | Week | Notes |
|---|---|---|---|
| Shortlist 8–15 papers | D | 1–2 | Human |
| License check per paper | D | 2 | Human |
| Write `corpus_index.md` | D | 2 | Human |
| Assign document-level splits | D | 5 | Human only — no paper in two splits |
| Write `splits.md` | D | 5 | Human |
| Freeze splits (commit + tag) | D | 5 | Human |

### 3.3 Annotation

| Task | Owner | Week | Notes |
|---|---|---|---|
| Write `guidelines_v1.md` | D (AI drafts) | 2 | Human finalizes every line |
| Annotate 100–150 real claims | D | 2–5 | Human only |
| Second annotator labels shared 40 | Any member | 5 | Scheduled Week 4 |
| Compute Cohen's κ | D (script) | 5 | Verify formula by hand |
| Adjudicate disagreements | D + second annotator | 5 | Human only |
| Write `disagreements.md` | D | 5 | Human |
| Final `claims_annotated.jsonl` | D | 5 | Committed after adjudication |

### 3.4 Synthetic Benchmark

| Task | Owner | Week | Notes |
|---|---|---|---|
| Write `docs/perturbations.md` | D | 3 | Human only — AI does not spec this |
| Define synthetic record schema | D | 3 | Human |
| Implement `synthetic.py` | AI (D reviews) | 3–4 | Tests written first |
| Hand-verify ≥10 examples per type | D | 3–4 | Human |
| Implement `builder.py` | AI (D reviews) | 5 | Seeded; deterministic |
| Freeze seed and commit benchmark | D | 5 | Human |
| Balance check per type | D | 7 | Human |

### 3.5 Evaluation Harness

| Task | Owner | Week | Notes |
|---|---|---|---|
| Define experiment matrix (8 configs) | D | 7 | Human |
| Write config JSON files | D | 7 | Human |
| Define `run_eval.py` CLI interface | D | 7 | Human writes interface; AI implements |
| Implement `runner.py` | AI (D reviews) | 7 | |
| Implement `classification.py` | AI (D reviews) | 7–8 | D checks math on sample |
| Implement `retrieval.py` | AI (D reviews) | 7–8 | |
| Implement `abstention.py` | AI (D reviews) | 7–8 | |
| Implement `bootstrap.py` | AI (D reviews) | 8 | D verifies CI on hand calc |
| Implement `calibration.py` | AI (D reviews) | 8–9 | |
| Implement `agreement.py` | AI (D reviews) | 5 | D verifies on hand calc |
| License-check and run SciFact/SciTab/TAT-QA adapters | D | 4–8 | Human decides which to include |
| Run dev-set evaluation (all 8 configs) | D | 8 | Human runs |
| Run test-set evaluation (once) | D | 10 | Human runs |

### 3.6 Web UI

| Task | Owner | Week | Notes |
|---|---|---|---|
| Sketch all 6 screens | D | 6 | Human only — must precede AI prompt |
| Scaffold `apps/web/` | AI (D reviews) | 6 | |
| `UploadPage` component | AI (D reviews) | 6–7 | |
| `DocumentList` with polling | AI (D reviews) | 6–7 | |
| `ClaimList` with filter + pagination | AI (D reviews) | 6–7 | |
| `ClaimDetail` with all 6 sections | AI (D reviews) | 6–7 | |
| `ReviewForm` | AI (D reviews) | 7 | |
| `RunHistory` | AI (D reviews) | 7 | |
| Typed API client (`src/api/`) | AI (D reviews) | 6–7 | Must match A's Pydantic shapes exactly |
| Frontend tests (Vitest + RTL) | AI (D reviews) | 7–8 | |
| Text escaping verification | D | 7 | Human verifies — inject `<script>` in a claim and confirm it is not executed |

### 3.7 Write-Up and Demo

| Task | Owner | Week | Notes |
|---|---|---|---|
| Introduction | D | 8–9 | Human |
| Related Work | D | 9 | Human |
| Methods | D | 9 | Human |
| Results | D | 10 | Human — numbers from harness only |
| Limitations | D | 10 | Human |
| Citation verification | D | 10 | Human only |
| Number traceability verification | D | 10 | Human only |
| `DEMO.md` | D | 10 | Human |
| Demo sample data preparation | AI assists | 10 | |

---

## 4. Annotated Record Schema

File: `evaluation/annotations/claims_annotated.jsonl` (one JSON object per line)

```json
{
  "annotation_id": "ann-001",
  "claim_id": "clm-001",
  "paper_id": "paper-007",
  "split": "dev",
  "claim_text": "Model A achieves 91.2% accuracy on the test set.",
  "claim_type": "quantitative",
  "source_anchor": {
    "page": 3,
    "element_type": "paragraph",
    "char_start": 142,
    "char_end": 198,
    "table_id": null,
    "row": null,
    "col": null
  },
  "numeric_slots": {
    "metric": "accuracy",
    "entity": "Model A",
    "value": "91.2",
    "unit": "%",
    "scale": null,
    "period": "test set",
    "comparison_basis": null,
    "denominator": null,
    "precision": 1,
    "rounding": "1 decimal"
  },
  "evidence_anchor": {
    "page": 5,
    "element_type": "table_cell",
    "table_id": "table-3",
    "row": 2,
    "col": 3
  },
  "verdict": "Supported",
  "abstention_reason": null,
  "annotator_id": "member-d",
  "adjudicated": false,
  "annotation_date": "2026-02-15",
  "notes": ""
}
```

Field notes:
- `claim_id` — must match the ID the pipeline assigns to this claim. Agree the hash formula with A in Week 1.
- `value` — string (Decimal) in the canonical display unit, not float. `"91.2"` with `unit: "%"`, not `"0.912"` with `unit: "%"`. Canonical representation rule must be agreed with A and B in Week 1.
- `adjudicated` — set to `true` when the second annotator disagreed and the record was resolved.
- `verdict` — one of the five claim-level `VerdictStatus` values. `Processing Error` is never a valid annotation label.

---

## 5. Synthetic Benchmark Record Schema

File: `evaluation/datasets/synthetic_benchmark.jsonl` (one JSON object per line)

```json
{
  "synthetic_id": "syn-0042",
  "source_annotation_id": "ann-001",
  "perturbation_type": "unit_incomparable",
  "perturbation_params": {
    "original_unit": "%",
    "perturbed_unit": "percentage_points",
    "conversion_defined": false
  },
  "perturbed_claim_text": "Model A achieves 91.2 percentage points accuracy on the test set.",
  "original_claim_text": "Model A achieves 91.2% accuracy on the test set.",
  "expected_verdict": "Needs Review",
  "expected_policy_rule": 3,
  "evidence_text": "Model A: 91.2% accuracy (test set)",
  "evidence_anchor": {
    "page": 5,
    "element_type": "table_cell",
    "table_id": "table-3",
    "row": 2,
    "col": 3
  },
  "seed": 42
}
```

---

## 6. Evaluation Harness — run_eval.py Output Schema

File written to `evaluation/results/{experiment}_{split}_{date}.json`:

```json
{
  "experiment": "full_system",
  "split": "dev",
  "run_timestamp": "2026-02-10T20:00:00Z",
  "policy_version": "v1.0",
  "config_file": "evaluation/baselines/configs/full_system.json",
  "n_claims": 75,
  "metrics": {
    "macro_f1": 0.77,
    "_note": "All metric values in this example are illustrative only. macro_f1 = mean(0.89, 0.62, 0.83, 0.79, 0.74) = 0.774, rounded to 0.77.",
    "per_class": {
      "Supported":           { "precision": 0.91, "recall": 0.88, "f1": 0.89, "support": 30 },
      "Contradicted":        { "precision": 0.87, "recall": 0.79, "f1": 0.83, "support": 14 },
      "Unsupported":         { "precision": 0.78, "recall": 0.81, "f1": 0.79, "support": 16 },
      "Needs Review":        { "precision": 0.72, "recall": 0.76, "f1": 0.74, "support": 10 },
      "Partially Supported": { "precision": 0.65, "recall": 0.60, "f1": 0.62, "support": 5 }
    },
    "confusion_matrix": {
      "labels": ["Supported", "Partially Supported", "Contradicted", "Unsupported", "Needs Review"],
      "matrix": [[26,1,1,2,0],[0,3,0,1,1],[1,0,11,1,1],[2,0,1,13,0],[1,0,1,0,8]]
    },
    "mismatch_detection": {
      "precision": 0.87,
      "recall": 0.79,
      "note": "Computed on claims with ground truth Contradicted due to numeric mismatch"
    },
    "abstention_rate": 0.133,
    "recall_at_1": 0.76,
    "recall_at_5": 0.91,
    "recall_at_10": 0.95,
    "source_anchor_accuracy": 0.88,
    "brier_score": 0.14
  },
  "bootstrap_ci_95": {
    "macro_f1": [0.80, 0.86],
    "recall_at_5": [0.87, 0.94],
    "n_bootstrap_samples": 1000,
    "resampling_unit": "document"
  },
  "risk_coverage": {
    "coverage": [1.0, 0.9, 0.8, 0.7, 0.6],
    "accuracy": [0.81, 0.85, 0.88, 0.91, 0.94]
  },
  "per_claim_predictions": [
    {
      "annotation_id": "ann-001",
      "claim_id": "clm-001",
      "expected": "Supported",
      "predicted": "Supported",
      "correct": true
    }
  ]
}
```

---

## 7. UI Component Details

### 7.1 Routing structure (`src/App.tsx`)

```
/                          → redirect to /projects
/projects                  → ProjectList (not in MVP scope — single project assumption OK)
/projects/:projectId       → DocumentList
/projects/:projectId/upload → UploadPage
/documents/:documentId/claims → ClaimList
/claims/:claimId           → ClaimDetail
/projects/:projectId/runs  → RunHistory
```

### 7.2 Polling logic (`DocumentList`)

```typescript
// Poll every 5 seconds for documents that are not yet in a terminal state
const TERMINAL_STATUSES = new Set(["complete", "error"]);
const POLL_INTERVAL_MS = 5000;

useEffect(() => {
  if (documents.every(d => TERMINAL_STATUSES.has(d.status))) return;
  const id = setInterval(() => refetch(), POLL_INTERVAL_MS);
  return () => clearInterval(id);
}, [documents, refetch]);
```

### 7.3 Text safety requirement

Every field that contains user-supplied or extracted text must render as plain text. In React this means using `{claim.claim_text}` not `dangerouslySetInnerHTML`. Write a test that injects `<img src=x onerror="alert(1)">` as a claim text and confirms no alert fires and the string renders literally.

### 7.4 `ClaimDetail` data flow

```
GET /claims/:id
  └── returns ClaimDetailResponse
        ├── claim fields (render in Section 1)
        ├── retrieved_evidence[] (render in Section 2)
        ├── nli_results[] (render in Section 3, matched by evidence_id)
        ├── numeric_checks[] (render in Section 4, matched by evidence_id)
        ├── verdict (render in Section 5)
        └── review_history[] (render in Section 6)
```

Match `nli_results` and `numeric_checks` to their evidence cards using `evidence_id`. If `nli_results` or `numeric_checks` is empty for an evidence item, show "Not available" in that section.

### 7.5 TypeScript interfaces (`src/types/api.ts`) — partial

```typescript
export type ClaimType =
  | "quantitative" | "comparative" | "temporal"
  | "citation" | "categorical" | "other";

export type VerdictStatus =
  | "Supported" | "Partially Supported" | "Contradicted"
  | "Unsupported" | "Needs Review";

// Note: "Processing Error" is NOT in VerdictStatus — it's a DocumentStatus

export type DocumentStatus = "queued" | "processing" | "complete" | "error";
export type NumericCheckResult = "match" | "mismatch" | "incomparable" | "not_applicable";
export type NLILabel = "entailment" | "contradiction" | "neutral";

export interface SourceAnchor {
  page: number;
  element_type: string;
  char_start: number | null;
  char_end: number | null;
  table_id: string | null;
  row: number | null;
  col: number | null;
  bounding_box: [number, number, number, number] | null;
}

export interface NumericSlots {
  metric: string | null;
  entity: string | null;
  value: string | null;        // Decimal string in canonical display unit (e.g., "91.2" for 91.2%)
  unit: string | null;
  scale: string | null;
  period: string | null;
  comparison_basis: string | null;
  denominator: string | null;
  precision: number | null;
  rounding: string | null;
}

export interface ClaimDetail {
  claim_id: string;
  document_id: string;
  project_id: string;
  claim_text: string;
  claim_type: ClaimType;
  extraction_method: string;
  extraction_confidence: number;
  source_anchor: SourceAnchor;
  // null for non-numeric claims; object with nullable fields for numeric claims with missing slots
  numeric_slots: NumericSlots | null;
  retrieved_evidence: RetrievedEvidence[];
  // empty array if NLI has not run or no evidence was retrieved
  nli_results: NLIResult[];
  // empty array if numeric check is not applicable or has not run
  numeric_checks: NumericCheck[];
  verdict: VerdictDetail;
  review_history: ReviewEvent[];
}
```

---

## 8. Evaluation Metrics Reference

| Metric | Formula | Notes |
|---|---|---|
| Precision (per class c) | TP_c / (TP_c + FP_c) | |
| Recall (per class c) | TP_c / (TP_c + FN_c) | |
| F1 (per class c) | 2·P·R / (P+R) | undefined when P+R=0, set to 0 |
| Macro-F1 | mean(F1_c for c in classes) | primary verdict metric |
| Mismatch detection precision | TP_contra / predicted_contra | only on numeric contradiction cases |
| Mismatch detection recall | TP_contra / actual_contra | |
| Abstention rate | \|Needs Review\| / \|total claims\| | |
| Risk-coverage | coverage = 1 − abstention_rate; accuracy = correct / (total − abstained) | sweep at different τ_ret thresholds |
| Recall@k | \|retrieved ∩ relevant\| / \|relevant\| | k ∈ {1, 5, 10} |
| Source-anchor accuracy | exact-match of top-1 anchor to annotated evidence anchor | page + table_id + row + col all must match |
| Cohen's κ | (P_o − P_e) / (1 − P_e) | inter-annotator agreement |
| Bootstrap CI | resample documents (not claims) 1000× with replacement; compute metric each time; 2.5–97.5 percentile | |
| Brier score | (1/N) Σ (p_entailment_i − y_i)² | **Binary calibration only:** y_i = 1 if true verdict is Supported, 0 otherwise; p_entailment_i is the NLI entailment probability. This measures calibration of the NLI component, not the full multi-class system. If the team wants multi-class calibration, discuss with C and adopt a multiclass ECE method instead — document the decision in `evaluation/metrics/calibration.py`. |

---

## 9. Deliverables Checklist

### Data and Annotation
- [ ] `evaluation/datasets/corpus_index.md` — all papers with licenses and splits
- [ ] `evaluation/datasets/splits.md` — frozen split documentation
- [ ] `evaluation/annotations/guidelines_v1.md` — annotation guidelines
- [ ] `evaluation/annotations/claims_annotated.jsonl` — 100–150 annotated real claims
- [ ] `evaluation/annotations/disagreements.md` — inter-annotator disagreements and resolutions, final κ score
- [ ] `evaluation/datasets/synthetic_benchmark.jsonl` — frozen synthetic benchmark
- [ ] `docs/perturbations.md` — perturbation spec

### Evaluation Harness
- [ ] `evaluation/run_eval.py` — CLI entry point
- [ ] `evaluation/baselines/configs/` — all 8 experiment configs
- [ ] `evaluation/baselines/runner.py` — experiment runner
- [ ] `evaluation/metrics/*.py` — all metric scripts
- [ ] `evaluation/results/full_system_test_FINAL.json` — final test-set results
- [ ] `evaluation/TEST_RUN_PROTOCOL.md` — completed with actual run date and hash

### Web UI
- [ ] `apps/web/` — complete React application, all 6 screens
- [ ] All UI components pass Vitest tests
- [ ] Text-injection security test passes

### Write-Up and Demo
- [ ] `docs/write_up_draft.md` — complete, all sections, all citations verified, all numbers from harness
- [ ] `DEMO.md` — complete demo script
- [ ] Final results reproducible from one command on a fresh clone
