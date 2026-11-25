# EvidenceGraph: Implementation Plan (4 People, AI-Assisted)

Companion to `EvidenceGraph_Framework.md` (v2). That file says **what** to build. This file says **who does what**, and which parts are **human work** and which are **AI work**.

---

## 1. How We Work With the AI IDE

### 1.1 Core rule

> **Humans decide, specify, label, review, and measure. The AI writes code against a human-written spec and tests.**

### 1.2 What is always human

| Area | Why |
|---|---|
| Contracts: Pydantic schemas, DB schema, API shapes, `DomainPack` interface | Everything else depends on them; AI changes to them cause silent breakage. |
| Decision policy rules and thresholds (τ values) | This is the research contribution; thresholds come from dev-set analysis. |
| Ground-truth labels (real annotated set, adjudication) | AI-labeled ground truth makes the evaluation circular. |
| Test cases for numeric logic (golden cases) | The tests define correct behavior; AI should not write both code and its oracle. |
| Reviewing every AI-generated PR | Accountability and learning. |
| License checks, dataset selection, model selection | Legal and methodological decisions. |
| Running evaluations, interpreting results, writing the report | The scientific claims must be owned by people. |
| Literature review and novelty statement | AI can hallucinate citations. Every citation must be opened and verified by a human. |
| Security sign-off | Needs judgment, not just generated tests. |

### 1.3 What is delegated to the AI

| Area | Condition |
|---|---|
| Boilerplate: FastAPI routes, SQLAlchemy models, Alembic migrations (from the human schema) | Must match the contract exactly. |
| Implementing a module to pass human-written tests | Tests exist before the prompt. |
| Unit tests for edge cases (in addition to human golden cases) | Human reviews that they test real behavior. |
| Docker, Compose, CI YAML | Human verifies it runs from a clean clone. |
| React UI components from a described layout | Human checks escaping and the trace display. |
| Synthetic perturbation generator code | Human defines perturbation types and labeling rules. |
| Metrics scripts, plotting, report/HTML export templates | Human checks numbers against a hand calculation. |
| Docstrings, README sections, refactors | Human skims diffs. |

### 1.4 Gray zone: AI drafts, human must verify

- Regex and rule patterns for claim extraction and slot parsing (AI drafts; human runs on the real corpus and fixes failures).
- Prompt text for any local LLM baseline.
- Annotation guideline drafts (humans finalize and apply).

### 1.5 AI-IDE working rules

Put these in `AGENTS.md` (or the IDE's rules file) at the repo root; each member reviews it in Week 1.

1. Read `domain/schemas.py` and `EvidenceGraph_Framework.md` before coding. Never change `domain/schemas.py`, `domain/policies.py`, or migrations without an explicit human instruction.
2. Work on one task card at a time; stay inside the listed files.
3. Tests first: run the existing tests, then make them pass. Do not delete or weaken tests to make them pass.
4. No new dependencies without asking. Only permissively licensed, free packages. No paid APIs, no network calls to hosted LLMs.
5. Never hard-code thresholds; read them from config.
6. Never invent values for missing slots; use `null`.
7. Use `Decimal` for numeric comparisons, never `float` equality.
8. Do not log document contents.
9. Finish by reporting: files changed, tests run, assumptions made, anything unverified.

### 1.6 Task-card template (use for every AI prompt)

```text
TASK: <one sentence>
CONTEXT: files to read: <paths>; contract: <schema/interface name>
SCOPE: you may edit only: <paths>
INPUTS/OUTPUTS: <types, example JSON>
ACCEPTANCE: these tests must pass: <paths>; plus: <extra conditions>
CONSTRAINTS: no new deps; zero-cost; follow AGENTS.md
REPORT BACK: files changed, tests run, assumptions, open questions
```

### 1.7 Review checklist for every AI-generated PR

- [ ] Matches the contract; no unrequested files or dependencies.
- [ ] Tests pass locally; at least one test would fail if the logic were wrong (try breaking the code).
- [ ] No silently guessed values, no swallowed exceptions, no hard-coded thresholds.
- [ ] Numeric code uses `Decimal`/Pint correctly.
- [ ] No secrets, no document text in logs, extracted text escaped in the UI.
- [ ] Reviewer is **not** the person who prompted it. Use cross-review (A reviews B, B reviews C, C reviews D, D reviews A).

### 1.8 Free-tier limits

AI IDE free tiers (including Antigravity) may rate-limit or change quotas; check the current limits yourselves. Plan around them:

- Keep task cards small so one prompt is one reviewable change.
- Budget prompts per week; do not spend quota on trivial edits.
- Keep a second free assistant as a fallback.
- Keep the repo in a state where any member can continue by hand.

---

## 2. Team Roles

Assign names to the four roles in the Week 1 meeting.

| Role | Name | Owns | Directories |
|---|---|---|---|
| **A: Platform and Integration Lead** | ____ | DB schema, API, job queue, worker orchestration, Docker, CI, provenance persistence, reports (JSON/HTML), final integration | `apps/api`, `persistence/`, `infra/`, `domain/provenance.py`, `worker/reporting`, CI |
| **B: Document and Numeric Lead** | ____ | PDF/CSV ingestion, source anchors, claim extraction, numeric-slot parser, numeric validators, scientific pack | `worker/ingestion`, `worker/extraction`, `worker/verification/numeric*`, `domain_packs/scientific_research` |
| **C: Retrieval and Verification Lead** | ____ | BM25, dense retrieval, fusion, reranker, NLI, decision policy implementation, calibration | `worker/retrieval`, `worker/verification/nli*`, `domain/policies.py` |
| **D: Evaluation, Data, and UI Lead** | ____ | Corpus, annotation, synthetic benchmark, metrics, ablations, literature review, web UI, write-up | `evaluation/`, `apps/web`, docs |

**Shared responsibilities:** weekly 45-minute sync; cross-review of PRs; each member keeps their own section of `README` and the license inventory current.

**Contracts owner:** all four write the contracts together in Week 1 (human work); A is the final editor and merges.

---

## 3. Branching and Integration Rules

- `main` is protected; merge via PR with one human approval from a different member and green CI.
- Branch per task card: `feat/<role>-<short-name>`.
- A member edits only their own directories; changes elsewhere go through the owner.
- **Contract change process:** open an issue, discuss in the weekly sync, update `domain/schemas.py` by hand, then regenerate dependent code with the AI.
- **Integration day:** end of every week, A merges, runs the Compose stack from a clean clone, and posts the result.
- **Mock-first:** until a module lands, others code against its interface with a stub that returns fixture data in the contract shape (AI can generate stubs from the schema).

---

## 4. Work Breakdown by Person

Legend: **H** = human work, **AI** = delegated to the AI IDE under the task-card rules.

### 4.1 Member A: Platform and Integration Lead

| Task | H | AI |
|---|---|---|
| Finalize DB schema from the provenance tables (Framework 3.7), review ER diagram | ✔ write column list, constraints, indexes | |
| SQLAlchemy models and Alembic migrations | review, run on a fresh DB | ✔ generate from schema |
| FastAPI endpoints: upload, list documents/claims, get claim trace, submit review, run analysis | define endpoint list and response JSON | ✔ implement routes, Pydantic models, HTTPX tests |
| File validation: extension, signature, size, page limits, hashing, safe paths | specify limits, threat list | ✔ implement and unit-test |
| Postgres `jobs` queue (`FOR UPDATE SKIP LOCKED`), retries, idempotency keys | design states and retry policy | ✔ implement worker loop and tests |
| Worker orchestrator that calls B and C modules via their interfaces | define stage order, failure behavior | ✔ implement wiring, structured logging |
| Provenance persistence: write verification results and `graph_edges` | define edge semantics for each verdict path | ✔ implement writers, trace query |
| Report export: JSON and static HTML report | design report content and wording of uncertainty | ✔ templates and generator |
| Docker Compose, `.env.example`, one-command start | verify from a clean machine | ✔ Dockerfiles, compose, healthchecks |
| GitHub Actions: lint, type check, tests, numeric regression, mini-eval gate | choose gates and pass criteria | ✔ write workflow YAML |
| Security tests: malformed files, oversized files, path traversal, duplicate submissions, worker restart | write the threat list, sign off | ✔ generate test cases |
| Reproducibility: pinned lockfiles, model revision pinning, rerun-identical test | decide what must be identical | ✔ script the rerun comparison |

**A's Definition of Done:** clean clone → `docker compose up` → upload → job completes → trace and report available; CI green.

### 4.2 Member B: Document and Numeric Lead

| Task | H | AI |
|---|---|---|
| Choose PDF parsing approach after trying pdfplumber on 5+ real papers; define `low_quality` anchor rules | ✔ test on the real corpus, decide | |
| Canonical document model and source anchors for paragraphs, table cells, CSV rows | define anchor id format | ✔ implement parser and anchors |
| Table extraction with header and caption/units association | review outputs manually on each corpus paper | ✔ implement; iterate on failures |
| Claim extraction rules: sentence split (spaCy), numeric patterns, metric keywords, table-row references | write 30+ labeled examples as tests | ✔ draft rules and code; ✔ fix failures |
| Numeric-slot parser (value, unit, scale, period, entity, denominator, rounding) | **specify slot grammar and normalization rules; write golden cases** (percent vs. points, "2.1M", "5-fold CV", etc.) | ✔ implement parser to pass golden cases |
| Numeric validators: slot matching, unit/scale normalization (Pint), tolerance from precision, `match/mismatch/incomparable/not_applicable` | **define tolerance rule and comparability rules; write golden test table** | ✔ implement; ✔ add edge-case tests |
| Calculation trace output (human-readable steps) | define trace format | ✔ implement |
| Scientific pack validators: unit/scale, period/condition, table-to-text, arithmetic consistency | define each validator's assumptions and limits | ✔ implement behind the `DomainPack` interface |
| Extraction and slot metrics on dev set (with D) | analyze errors, decide fixes | ✔ error-analysis scripts |

**B's Definition of Done:** all golden numeric cases pass; slot accuracy at least 0.95 on dev set (or documented reason); extraction recall measured and reported.

### 4.3 Member C: Retrieval and Verification Lead

| Task | H | AI |
|---|---|---|
| Select and license-check embedding, reranker, and NLI models; record revisions | ✔ choose, verify licenses and CPU latency | |
| Chunking strategy for paragraphs, table segments, CSV rows; window expansion (headers, units, captions) | decide chunk and window rules | ✔ implement |
| BM25 (`rank_bm25`), dense retrieval (pgvector), reciprocal-rank fusion, dedup | define k values and fusion parameters | ✔ implement with tests |
| Cross-encoder reranking | decide top-k to rerank | ✔ implement and batch |
| Retrieval metrics: Recall@k, anchor accuracy (with D) | read results, diagnose misses | ✔ metric script |
| NLI wrapper: label, probabilities, revision; batching; caching to disk by hash | define stored fields | ✔ implement |
| **Decision policy v1** from Framework 4.8: human writes the rule table as test cases (input combination to expected verdict) | ✔ write 25+ policy test cases; decide τ definitions | ✔ implement `policies.py` function to pass them (thresholds from config) |
| Threshold calibration on dev split: sweep τ_ret, τ_e, τ_c, τ_ext; choose by risk-coverage trade-off | ✔ choose thresholds and justify; freeze policy | ✔ sweep scripts and plots |
| Calibration analysis (Brier/ECE) and abstention-reason breakdown | interpret | ✔ scripts |
| Optional: local LLM judge baseline via Ollama, only if hardware allows | decide whether to include | ✔ wrapper and prompt draft |

**C's Definition of Done:** Recall@5 measured on dev; NLI outputs persisted; policy passes all human-written cases; thresholds chosen on dev and recorded in a policy version.

### 4.4 Member D: Evaluation, Data, and UI Lead

| Task | H | AI |
|---|---|---|
| Literature check: numeric claim verification, table fact-checking (SciFact, SciTab, FEVEROUS, TAT-QA and related); write the related-work and novelty paragraph | ✔ find, read, verify every citation | (AI may suggest search keywords only) |
| Select 8-15 public papers with result tables and supporting CSVs; check licenses; split by document into train/dev/test | ✔ | |
| Annotation guidelines (claim span, slots, verdict, evidence anchor, abstention cases) | ✔ finalize | AI drafts a first version |
| Annotate 100-150 real claims; second annotator (any member) labels a shared 40-claim subset; compute agreement; adjudicate | ✔ | |
| Synthetic perturbation generator: number change, in-tolerance rounding, unit/scale swap, period swap, percent vs. points, entity swap, evidence removal, low-quality table | ✔ define perturbation types and the verdict each must receive | ✔ implement generator and dataset builder (seeded, reproducible) |
| Evaluation harness: run pipeline versions on splits, produce tables and plots | define metrics and baseline configurations | ✔ metrics code, bootstrap CIs by document, risk-coverage plots |
| Baselines and ablations (BM25+NLI; hybrid+NLI; +rerank; +numeric; minus dense/rerank/context/abstention) | decide the experiment matrix; run; interpret | ✔ configs and runner |
| External sanity checks on SciFact/SciTab/TAT-QA (component-level) | verify license and decide what to run | ✔ adapters |
| Web UI: upload page, claim list with status filter, claim detail (evidence, source anchor, NLI, numeric trace, abstention reason), review form, run history | sketch each screen; choose what to show | ✔ React components, API client, tests |
| UI safety: escaped text, no raw HTML rendering | verify | ✔ implement |
| Final write-up: methods, results, limitations, reproducibility | ✔ write | AI may help edit wording; every number must come from the harness |
| Demo script and (optional) recorded walkthrough | ✔ | ✔ help prepare sample data |

**D's Definition of Done:** sealed test set exists; harness reproduces every number in the report from a single command; UI shows a complete trace.

---

## 5. Week-by-Week Plan

Each row lists human (H) and AI work. All members attend the weekly sync and do cross-review.

### Week 1: Contracts and setup
| Who | H | AI |
|---|---|---|
| All | Agree scope (Framework v2); write `domain/schemas.py` (claim, slots, anchor, verdict, result types), DB table list, API list, `DomainPack` interface, `AGENTS.md`; assign roles | |
| A | Repo, branch protection, Compose skeleton | AI: Dockerfiles, compose, empty FastAPI app with health route, CI skeleton |
| B | Try pdfplumber on candidate papers | AI: small scripts to dump text/tables per page |
| C | Shortlist models; check licenses and CPU speed | AI: benchmark script for latency |
| D | Start literature check; shortlist public papers | AI: nothing critical |

**Gate:** contracts frozen as v0; clean clone runs the Compose skeleton; license inventory started.

### Week 2: Ingestion and data foundations
| Who | H | AI |
|---|---|---|
| A | Finalize schema | AI: models, migrations, upload endpoint, validation, `jobs` queue |
| B | Define anchor format and `low_quality` rules | AI: parser, anchors, CSV rows, tests |
| C | Define chunking and window rules | AI: chunker (stub-compatible) |
| D | Finalize corpus and splits; guidelines v1; begin annotating | AI: draft guideline text |

**Gate:** upload a PDF and CSV and see anchored chunks in the DB.

### Week 3: Claims and slots
| Who | H | AI |
|---|---|---|
| B | Write claim and slot golden cases (30+) | AI: extraction rules and slot parser |
| A | Define claim/ review endpoints | AI: endpoints and tests |
| C | Prepare retrieval test queries from annotated claims | AI: BM25 index and tests |
| D | Continue annotation; build synthetic generator spec | AI: generator v0 |

**Gate:** extraction precision/recall and slot accuracy measured on the dev set.

### Week 4: Retrieval
| Who | H | AI |
|---|---|---|
| C | Choose k and fusion parameters; analyze misses | AI: dense retrieval, fusion, reranker, Recall@k script |
| B | Fix extraction failures found by retrieval misses | AI: patches with tests |
| A | Define stage order and failure behavior | AI: orchestrator wiring for ingestion to retrieval |
| D | Annotation continues; agreement subset labeled | AI: metrics adapters |

**Gate:** Recall@5 on the dev set reported; baseline 1 and 2 configurations runnable.

### Week 5: NLI and numeric validators
| Who | H | AI |
|---|---|---|
| B | Write validator golden table (tolerance, units, comparability) | AI: validators, traces, Pint integration |
| C | Define NLI stored fields; start policy test cases | AI: NLI wrapper, batching, caching |
| A | Define verification-result and edge semantics | AI: persistence of results and edges |
| D | Synthetic generator v1 (all perturbation types); compute inter-annotator agreement | AI: dataset builder |

**Gate:** each claim has stored NLI and numeric results with traces.

### Week 6: Policy and first end-to-end milestone
| Who | H | AI |
|---|---|---|
| C | Finish 25+ policy tests; review decision logic | AI: policy implementation |
| A | Run the Framework Section 11 scenario end to end; lead debugging | AI: fix integration bugs |
| B | Scientific pack validators reviewed on real examples | AI: pack implementation |
| D | Sketch UI screens; prepare scenario data with an introduced inconsistency | AI: UI scaffold |

**Gate (E2E milestone):** all 8 points of Framework Section 11 pass. **Scope freeze:** no new features after this week.

### Week 7: UI, reports, benchmark
| Who | H | AI |
|---|---|---|
| D | Review UI against sketches; finalize synthetic set and freeze splits | AI: UI screens, evaluation runner |
| A | Report design | AI: JSON/HTML export |
| B | Error analysis on synthetic failures | AI: fixes with tests |
| C | First threshold sweeps on dev | AI: sweep scripts |

**Gate:** reviewer can open a claim and see the full trail; report exports.

### Week 8: Evaluation v1
| Who | H | AI |
|---|---|---|
| D | Run baselines and ablations on dev; interpret | AI: tables, plots, CIs |
| C | Choose thresholds draft | AI: risk-coverage curves |
| A | Security test list; fix CI gates | AI: test generation |
| B | Fix top numeric error categories | AI: patches with tests |

**Gate:** first results tables; list of the top failure modes.

### Week 9: Calibration and hardening
| Who | H | AI |
|---|---|---|
| C | **Freeze policy version and thresholds** (dev only) | AI: final sweep reports |
| A | Security sign-off; reproducibility rerun check | AI: robustness tests |
| B | Final slot/validator fixes on dev only | AI: patches |
| D | Prepare held-out test run protocol; draft write-up | AI: report skeleton from harness outputs |

**Gate:** policy frozen; no test-set access before this point.

### Week 10: Final run and write-up
| Who | H | AI |
|---|---|---|
| D | Run the sealed test split once; record all results honestly, including negative ones | AI: produce tables and figures |
| All | Write limitations, reproducibility instructions; verify citations; rehearse demo | AI: wording edits only |
| A | Tag release, pin lockfiles, clean-clone check | AI: release scripts |

**Gate:** results reproducible from one command; write-up complete; demo ready.

---

## 6. Example Task Cards (copy and adapt)

**B: slot parser**
```text
TASK: Implement parse_numeric_slots(claim_text, context) -> NumericSlots.
CONTEXT: read domain/schemas.py (NumericSlots), tests/regression/test_slots_golden.py
SCOPE: edit only worker/extraction/slots.py and tests/unit/test_slots_extra.py
ACCEPTANCE: all tests in test_slots_golden.py pass; unknown slots are None, never guessed
CONSTRAINTS: Decimal for values; percent and percentage points are different units; no new deps
REPORT BACK: files changed, tests run, assumptions, golden cases you think are wrong
```

**B: numeric validator**
```text
TASK: Implement compare_slots(claim_slots, evidence_slots) -> NumericCheck.
CONTEXT: domain/schemas.py (NumericCheck), tests/regression/test_numeric_golden.py
SCOPE: worker/verification/numeric.py only
ACCEPTANCE: golden table passes; incomparable is returned when metric, entity, period, or denominator does not match
CONSTRAINTS: tolerance from stated precision per the rule in docs; use Pint for units; include a human-readable trace list
```

**C: decision policy**
```text
TASK: Implement decide(inputs, thresholds) -> Verdict per Framework 4.8.
CONTEXT: tests/unit/test_policy_cases.py (human-written), domain/schemas.py
SCOPE: domain/policies.py only
ACCEPTANCE: all policy cases pass; rules evaluated in order; reason code returned with each verdict
CONSTRAINTS: thresholds only from config; no hard-coded numbers
```

**A: job queue**
```text
TASK: Implement a Postgres-backed job queue with SELECT ... FOR UPDATE SKIP LOCKED.
CONTEXT: persistence/models.py (jobs), tests/integration/test_jobs.py
SCOPE: worker/queue.py, tests
ACCEPTANCE: two workers never take the same job; failed jobs retry up to N times with backoff; duplicate idempotency key is ignored
```

**D: synthetic generator**
```text
TASK: Build a seeded generator that perturbs claims from evaluation/datasets/source_claims.jsonl.
CONTEXT: perturbation table in docs/perturbations.md (human-written: type to expected verdict)
SCOPE: evaluation/datasets/synthetic.py and tests
ACCEPTANCE: same seed gives identical output; each record includes perturbation type, expected verdict, source anchor; counts per type are balanced
```

---

## 7. Risks to Delivery and Rules to Avoid Them

| Risk | Rule |
|---|---|
| AI produces plausible but wrong numeric logic | Human-written golden tests first; the AI may add tests but not remove or edit golden cases. |
| One person becomes a bottleneck | Cross-review rotation; A integrates but does not review everything. |
| Contracts drift | Contract change process (Section 3); changes in `domain/` need all four to know. |
| Circular evaluation | Test labels never come from the AI; thresholds set on dev only; test run once. |
| Quota exhaustion | Small task cards, weekly prompt budget, fallback assistant, hand-edit small fixes. |
| Hallucinated citations or numbers in the write-up | Every citation opened by a human; every number traced to the harness output. |
| Scope creep | Scope freeze at the end of Week 6; new ideas go to a "future work" list. |
| Dependent work blocked | Stubs in the contract shape from Week 1; mock-first. |

---

## 8. Final Deliverables Checklist

- [ ] Running system from `docker compose up` on a clean clone
- [ ] Section 11 end-to-end milestone passes and is reproducible
- [ ] Human-written golden tests for numeric slots, validators, and policy
- [ ] Synthetic benchmark generator (seeded) and annotated real set with agreement score
- [ ] Ablation table, risk-coverage curves, per-class results, bootstrap CIs, from one command
- [ ] Sealed test split run once with a frozen policy version
- [ ] License inventory for dependencies, models, and datasets
- [ ] Related-work and novelty paragraph with verified citations
- [ ] Limitations section (single domain, text PDFs only, English, CPU-only)
- [ ] Demo script or recording
