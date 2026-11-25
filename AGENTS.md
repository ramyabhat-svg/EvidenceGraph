# AGENTS.md — EvidenceGraph (rules for AI coding agents)

Applies to every task in this repository. Read it fully before acting. If a task prompt
conflicts with this file, stop and ask the human instead of guessing.

You are working for **Member A (Platform and Integration Lead)** of a four-person team.
Members B, C and D own other modules. Your code must plug into theirs without breaking
anything they already have.

---

## 1. Quality bar

The result must be top-notch, production-grade work that a strict reviewer would approve:

- Correct first, then simple, then fast. No clever tricks, no dead code, no commented-out code.
- Every public function, class and endpoint is typed, documented (short docstring) and tested.
- Every test must be able to fail: if the logic were wrong, a test would go red.
- Errors are handled deliberately: specific exception types, structured error responses,
  no bare `except`, no swallowed errors.
- Writes are idempotent where a retry can happen (jobs, ingestion, persistence).
- Nothing is hard-coded that belongs in configuration. Thresholds are never hard-coded.
- Small, readable diffs. Do not reformat or "improve" code outside the task scope.
- Documentation is updated in the same change as the code it describes.

## 2. Project context (verified against the repo)

EvidenceGraph verifies claims in scientific/technical reports against evidence with full
provenance. Pipeline: ingest PDF/CSV, anchor sources, extract claims and numeric slots,
retrieve evidence, verify (NLI + numeric), decide a verdict (with abstention), persist
provenance, report.

Stack: Python 3.10+ (write 3.10-compatible code), FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync),
psycopg 3, Alembic, PostgreSQL + pgvector, Docker Compose, pytest, ruff, mypy, GitHub Actions.
Services: `web` (Member D), `api`, `worker`, `postgres`.

Reference documents are in `docs/reference/` (including Member D's `handoff_to_member_A.md`, the frontend/API contract). Read the ones named in your task prompt.

Verified facts about Member B's code (base commit `d79d858`, branch `memberB`,
123 tests passing):

| Fact | Consequence for A's code |
|---|---|
| `worker.ingestion` exposes `ingest_pdf(path, document_id, file_hash) -> list[EvidenceChunk]` and `ingest_csv(...)` | There is no `ingest_document` dispatcher yet. A writes an adapter in `worker/orchestration/` that dispatches by file type and prefers B's `ingest_document` if it appears later. |
| `ingest_pdf` raises `ScannedPdfError` for image-only PDFs | The adapter converts it to `processing_error="scanned_pdf_unsupported"`; any other parse exception becomes `"parse_failed"`. Never crash the worker. |
| `extract_claims(chunks, file_hash) -> list[Claim]` uses paragraph chunks only | Call it per document with that document's chunks. |
| `verify_numeric_claim(claim, evidence_chunks, config=None) -> list[SlotVerification]` | The parameter is named `config` in code (`cfg` in the handoff text). Call it positionally. |
| `SlotVerification` is a dataclass in `worker/verification/numeric.py`; `NumericConfig` is there too; `ValidationResult` is in `domain_packs/scientific_research/pack.py` | They are not in `domain/schemas.py`. Import from where they live and write explicit serializers. |
| `ScientificResearchPack().validate(claim, evidence)` internally calls numeric verification again | Persist both outputs separately. Duplicate compute is acceptable. |
| Claim and chunk ids are deterministic UUIDv5 values derived from file hash + anchor (not from `document_id` or `run_id`) | The same file in two documents or two runs yields the same ids. Never use B's ids as primary keys. Store them as `extractor_claim_id` / `source_chunk_id` and derive A's own primary keys (see `eg_common/ids.py`). Claim ids are document-scoped and stable across runs: `derive_uuid(document_id, source_anchor_id, char_start, char_end)` (Member D's evaluation matches predictions by claim id); run results hang off (claim, run). |
| `NumericSlots.value`, `tolerance`, `difference` are `Decimal` | Store in unconstrained `NUMERIC`; serialize to JSON as strings; never use `float`. |
| README says Python 3.13, compiled files show 3.10, handoff says 3.10+ | Docker uses `python:3.11-slim`. Keep code 3.10-compatible. |
| `config/numeric.yaml` is mentioned in B's README but does not exist | `NumericConfig` comes from the run configuration (`approx_multiplier`, default `"2"`). |
| `claims.py` falls back to a blank spaCy sentencizer when `en_core_web_sm` is missing | Behaviour differs by environment. Record the model status in the run's `model_versions`, and pin the model in Docker. |

If a fact above turns out to be wrong when you check, report it. Do not silently adapt.

## 3. Ownership map

| Area | Owner | Rule for you |
|---|---|---|
| `eg_common/`, `domain/entities.py`, `domain/provenance.py`, `persistence/`, `apps/api/`, `worker/jobqueue.py`, `worker/main.py`, `worker/orchestration/`, `worker/reporting/`, `infra/`, `.github/`, `docker-compose.yml`, `.env.example`, `alembic.ini`, `pyproject.toml`, `requirements-api.txt`, `requirements-dev.txt`, `constraints.txt`, `docs/platform/`, `docs/integration/`, `docs/api.md`, `tests/integration/`, `tests/security/`, `tests/unit/platform/`, `tests/fixtures/platform/`, A's new files in `scripts/` | Member A | You may create and edit these, within the scope the task states. |
| `worker/ingestion/`, `worker/extraction/`, `worker/verification/numeric.py`, `domain_packs/`, `domain/schemas.py`, `tests/regression/`, B's existing tests in `tests/unit/`, `requirements.txt`, `pytest.ini`, `README.md`, `scripts/pdf_spike.py` | Member B | **Read-only.** |
| `worker/retrieval/`, `worker/verification/nli*`, `domain/policies.py` | Member C | Do not create or edit. Use the interfaces in `worker/orchestration/interfaces.py`. |
| `evaluation/`, `apps/web/` | Member D | Do not create or edit. A's annotation import script lives in `scripts/` unless D agrees otherwise. |
| `.gitignore` | shared | Additive edits only, and only when the task says so. |

If you need a change in someone else's area, do not make it. Write an entry in
`docs/integration/requests-for-member-<x>.md` (what, why, exact proposed change) and build an
adapter inside A's area instead. Changes to shared schemas or migrations happen only when the
task explicitly authorizes them.

## 4. Orientation protocol (before writing any code)

1. Run `git status`, `git branch --show-current`, `git log --oneline -5`. Confirm you are on a
   feature branch for this task and the tree has no changes other than files the human told you to expect. If not, stop and tell the human.
2. Read every file the task lists under READ FIRST, plus the public signatures of any module you
   will call. Do not rely on this file's summary alone.
3. Run the existing tests. Report the exact result. The baseline must be green before you edit
   (B's 123 tests, plus whatever earlier phases added). If it is red, stop and report why.
4. Write a short plan: files to create or change, order of work, risks, and every place your
   change touches another member's code. Then implement.
5. If the task and the repo contradict each other (for example a function does not exist), report
   the contradiction in the final report and choose the option that changes the least in other
   members' areas.

## 5. Compatibility rules

- Reuse B's Pydantic models as they are. Never copy or redefine them in A's code.
- Do not duplicate `filename`, `file_hash` or `storage_path` inside B's objects. A's `Document`
  owns them.
- Convert between B's objects and database rows only in `persistence/mappers.py`, and cover each
  mapper with a round-trip test using B's real models (including `Decimal` exactness).
- A contract-coverage test must fail if B adds a field that A does not persist.
- Never call something a mock of B or C when it is a stub: stubs live in
  `worker/orchestration/stubs.py`, are labelled with a version string such as `stub-*-v0`, and the
  run record states which components were stubs.
- Unknown values stay `None`. Never invent a number, unit, period or entity.
- Evidence must never be the claim's own source chunk.
- Additive columns or tables beyond the spec are allowed only when needed, and must be written in
  `docs/integration/decisions.md` with the reason.
- **Frontend contract (Member D).** The React client is built from
  `docs/reference/handoff_to_member_A.md`. The Pydantic response models in `apps/api/schemas/` are the
  source of truth for the TypeScript types: never rename or retype a response field; only add optional
  nullable fields. Regenerate `docs/openapi.json` whenever a response shape changes.
- API prefix is `/api/v1`. Every non-422 error body is
  `{"error": "<snake_case_code>", "message": "<safe text>", "field": <name or null>}`. 422 stays
  FastAPI's default. Never return stack traces or document text in errors.
- Enum strings are frozen and identical in Pydantic, database CHECK constraints and TypeScript:
  ClaimType `quantitative|comparative|temporal|citation|categorical|other`; VerdictStatus
  `Supported|Partially Supported|Contradicted|Unsupported|Needs Review` (claim verdicts only;
  "Processing Error" is document-level, never a claim verdict or claims-list filter value);
  DocumentStatus `queued|processing|complete|error`; NumericCheckResult
  `match|mismatch|incomparable|not_applicable`; NLILabel `entailment|contradiction|neutral`.
- If a task prompt and the handoff disagree on a field name or enum value that the frontend sees,
  the handoff wins. Report the disagreement.

## 6. Engineering rules

- Python 3.10-compatible: no `StrEnum`, `typing.Self`, `tomllib`, `datetime.UTC`. Use
  `datetime.now(timezone.utc)`.
- Type hints everywhere; `mypy` clean on A's packages; `ruff` clean (line length 100).
- SQLAlchemy 2.0 typed style (`Mapped[...]`). No string-built SQL. Use
  `with_for_update(skip_locked=True)` for the queue. Explicit transactions.
- Timestamps are timezone-aware UTC (`TIMESTAMPTZ`). IDs are UUIDs. Enums are stored as
  `VARCHAR` with named `CHECK` constraints.
- Settings only through `eg_common/settings.py` (environment variable names are unprefixed and match `.env.example`: `DATABASE_URL`, `CORS_ORIGINS`, `API_PORT`, `STUB_MODE`, `EVIDENCEGRAPH_ENV`, ...). `.env.example` holds
  placeholders only. No secrets in the repo, ever.
- Logging only through `eg_common/logging.py` (structured JSON with project, document, run and
  job ids). **Never log document text, claim text, evidence text or file contents.** Log ids,
  counts, durations, error codes.
- Error messages stored in the database or returned by the API contain codes and ids, never
  document text.
- Treat uploaded files and extracted text as untrusted data: never execute, never interpolate
  into SQL or shell, escape in HTML (Jinja2 autoescape on).
- Tests: pytest, deterministic, no network, no real sleeps (inject a clock), no dependence on test
  order. Put A's tests only in A's test folders (see section 3). Integration tests use
  `TEST_DATABASE_URL`; when `CI=true` and it is unset, a guard test must fail instead of
  skipping.
- New dependencies: only those the task names, in `requirements-api.txt` (runtime) or
  `requirements-dev.txt` (dev only). Open-source, permissive licence, no paid services, no
  hosted LLM calls. Allowed in A's area: fastapi, uvicorn, sqlalchemy, alembic, psycopg[binary],
  python-multipart, pydantic-settings, jinja2, httpx, ruff, mypy, pytest-cov, pip-audit,
  reportlab (dev, fixture generation only). Anything else: ask.
- Never delete, skip, weaken or edit B's tests or golden cases to make something pass.

## 7. Git protocol — the human runs git, you do not

You prepare the work. The human reviews the diff and runs every state-changing git command.

**Allowed (read-only):** `git status`, `git diff`, `git diff --stat`, `git log`, `git show`,
`git branch --show-current`, `git ls-files`, `git check-ignore`.

**Forbidden:** `git add`, `commit`, `push`, `pull`, `fetch`, `merge`, `rebase`, `reset`,
`checkout`, `switch`, `stash`, `tag`, `rm`, `mv`, `config` (writes), remote changes, the `gh`
CLI, and anything that contacts GitHub or authenticates. If a file must move, move it on disk and
tell the human which git commands to run.

**Authorship.** All commits are made by the human under their own identity. Never add
`Co-authored-by`, `Signed-off-by` or any trailer. Never mention an AI tool, assistant, agent or
model in commit messages, PR text, code comments or generated files. Do not add "generated by"
headers.

**Commit hygiene** (plan these in the final report):

- Atomic commits, one logical change each, ordered so the tree builds and tests pass at every
  commit. Code and the tests for it go together. Docs-only changes get their own commit.
  Cleanups of other members' files are never mixed with feature work.
- Conventional Commits: `type(scope): subject` — types `feat`, `fix`, `test`, `docs`, `build`,
  `ci`, `chore`, `refactor`; scopes `api`, `db`, `worker`, `queue`, `domain`, `report`, `infra`,
  `ci`, `security`, `docs`. Subject is imperative, lowercase, at most 72 characters, no final
  period. Body (second `-m`) explains why and notable decisions, wrapped near 72 characters.
- Stage by explicit path only. Never `git add .` or `git add -A`.
- Before staging, check `git status --short` for stray files (compiled Python, `.env`, `storage/`,
  caches, editor files, large binaries).
- Give shell-neutral commands that work in PowerShell, cmd and bash: one command per line, no
  `&&`, no line continuations, double-quoted `-m` strings that contain no backticks, `$`, `!`, `&`,
  `|`, `<`, `>` or `^`.
- Branches: `feat/a-p<N>-<short-name>`, created from the agreed BASE branch (the human tells you;
  it is `memberB` until a `main` exists). One branch and one pull request per phase.
- Pull requests are reviewed by Member D (review rotation: A reviews B, B reviews C, C reviews D,
  D reviews A). Never instruct the human to force-push, rewrite shared history or push to the base
  branch directly.

## 8. Final report (always end with this, in this order)

1. **Summary** — what was built, in a few lines.
2. **Files changed** — grouped as created / modified, one line each. State explicitly that no
   file in Member B, C or D areas was modified (or list each exception and why).
3. **Compatibility findings** — contradictions, risks and anything others must confirm; the new
   entries you added to `docs/integration/`.
4. **Verification** — exact commands you ran and their results (test counts, ruff, mypy, alembic,
   docker). Mark anything you could not run as UNVERIFIED and say why.
5. **Assumptions and open questions.**
6. **Human checklist** — commands for the human to run to verify the work (copy-paste ready).
7. **GIT HANDOFF** — in this order:
   1. Preconditions: `git status`, `git branch --show-current`, `git config user.name`,
      `git config user.email` (author must be the human's real GitHub identity).
   2. Create the branch from BASE.
   3. Commit sequence: for each commit give purpose, the explicit `git add <paths>` line, a
      `git status --short` check, and the `git commit -m "..." -m "..."` line.
   4. Pre-push audit: `git log --oneline <BASE>..HEAD`; author and trailer check with
      `git log <BASE>..HEAD --format="%h %an <%ae>%n%(trailers)"`; `git diff <BASE>...HEAD --stat`;
      confirm `git ls-files "*.pyc"` prints nothing new.
   5. Push: `git push -u origin <branch>`.
   6. Pull request: base branch, title, and a Markdown body (summary, changes, how it was
      tested, compatibility notes, risks, reviewer checklist; reviewer is Member D).
   7. After approval and merge: update BASE locally and delete the local branch.
8. **Notes for other members** — short, concrete items for B, C or D if any.
