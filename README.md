# EvidenceGraph — Integrated Research Evidence Verification Backend

## 1. Overview

EvidenceGraph is an integrated backend for checking claims in research documents against supplied
document evidence. It ingests a PDF and an optional companion CSV, anchors extracted passages and
table data to source locations, extracts claims and numeric slots, retrieves related evidence,
performs numeric and semantic checks, and stores verdicts with their evidence provenance.

The FastAPI service accepts documents and reports processing status and persisted analysis results.
A separate background worker performs parsing and model inference. Retrieval and inference run
locally on CPU. Verdict generation returns **Needs Review** when required policy thresholds have
not been calibrated and configured.

---

## 2. Architecture and Project Responsibilities

### Integrated processing flow

```text
PDF + optional companion CSV
            |
            v
FastAPI intake -> durable file storage -> queued document in PostgreSQL
                                            |
                                            v
                                   Background worker
                                            |
                  +-------------------------+----------------------+
                  v                         v                      v
            PDF/CSV parsing           Source anchors        Claim extraction
                  |                                                |
                  +------ persisted chunks and numeric slots -----+
                                            |
                                            v
                  BM25 + dense pgvector retrieval -> reciprocal rank fusion
                                            |
                      +---------------------+--------------------+
                      v                     v                    v
                Numeric checks          Local CPU NLI       Local reranker
                      +---------------------+--------------------+
                                            |
                                            v
                               Ordered decision policy
                                            |
                                            v
                      Persisted verdict, explanation and provenance
                                            |
                                            v
                               FastAPI status/verdict read-back
```

### Responsibilities

| Owner | Responsibilities |
|---|---|
| Member A — platform and integration | FastAPI intake and read APIs, PostgreSQL persistence and Alembic migrations, settings, worker orchestration, model adapters, and deployment configuration |
| Member B — document processing | PDF and companion CSV parsing, source anchors, claim and numeric-slot extraction, evidence-slot extraction, numeric verification, and the Scientific Research Pack |
| Member C — retrieval and policy | BM25 and pgvector dense retrieval, reciprocal rank fusion, local NLI and reranking, and ordered verdict decisions |
| Member D — evaluation and frontend | Development/evaluation data, threshold calibration, evaluation metrics, and the React frontend; these remain outstanding responsibilities |

The backend components are integrated under `apps/`, `persistence/`, and `worker/`. Embeddings use
the pinned `sentence-transformers/all-MiniLM-L6-v2` model (384 dimensions); NLI uses
`cross-encoder/nli-MiniLM2-L6-H768`; and relevance ranking uses
`cross-encoder/ms-marco-MiniLM-L6-v2`. Inference is local and CPU-only. Model revisions are pinned
in the corresponding worker orchestration modules. The current repository does not contain the
frontend or an evaluation dataset.

---

## 3. Project Structure

This is the current backend repository layout. It lists existing paths and omits generated files
and local environment contents.

```text
EvidenceGraph/
├── apps/api/                 # FastAPI app, document routes and response schemas
├── domain/                   # Shared schemas and domain entities
├── domain_packs/scientific_research/ # Scientific Research Pack and lexicon
├── eg_common/                # Settings, IDs, errors and structured logging
├── persistence/
│   ├── migrations/versions/  # Alembic revisions 0001 through 0005
│   ├── mappers.py
│   ├── models.py
│   ├── repositories.py
│   └── session.py
├── worker/
│   ├── extraction/           # Claims, numeric slots and evidence slots
│   ├── ingestion/            # PDF/CSV parsers and source anchors
│   ├── orchestration/        # Ingestion, embeddings, retrieval, verification and verdict flow
│   ├── verification/         # Numeric verification
│   └── main.py               # Background worker entrypoint
├── scripts/
│   ├── backfill_embeddings.py
│   └── pdf_spike.py
├── tests/
│   ├── integration/
│   ├── regression/
│   └── unit/
├── docs/
│   ├── api.md
│   ├── openapi.json
│   ├── integration/
│   └── platform/
├── infra/docker/             # API and worker Dockerfiles
├── .github/workflows/ci.yml
├── AGENTS.md
├── EvidenceGraph_Framework.md
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── pyproject.toml
├── pytest.ini
├── requirements.txt
├── requirements-api.txt
├── requirements-dev.txt
└── uv.lock
```

The listing reflects this checkout; it does not imply that the frontend or evaluation components
described in the project plan are present.

---

## 4. Technology Stack

`pyproject.toml` declares `requires-python = ">=3.10"`; source compatibility is Python 3.10 and
later. The current verified development environment uses Python 3.11.18, and the Docker images use
Python 3.11. The project does not require Python 3.13.

| Technology | Purpose |
|---|---|
| Python 3.10+ | Declared source compatibility; current development uses Python 3.11.18 |
| FastAPI, Pydantic v2 | HTTP API, request/response contracts and validation |
| SQLAlchemy 2.0, psycopg 3, Alembic | Synchronous PostgreSQL access and schema migrations |
| PostgreSQL 16, pgvector | Durable records, provenance and 384-dimensional cosine-vector search |
| pdfplumber, spaCy | PDF text/table extraction and claim sentence segmentation |
| sentence-transformers and PyTorch | Pinned local CPU embeddings, NLI and reranker inference |
| Decimal, Pint | Exact numeric values and unit-aware numeric verification |
| uv | Lockfile-based Python environment and dependency synchronization |
| PyYAML | YAML parsing support |
| pytest, Ruff, mypy | Tests, linting and static type checking |

---

## 5. Core Implementation Modules

### 5.1 Shared Domain Schemas

**File:** `domain/schemas.py`

Defines structured data contracts shared by the document-processing and integrated backend
pipelines.

Important models:

- `SourceAnchor`: Identifies the original location of extracted content.
- `EvidenceChunk`: Represents an extracted paragraph, table row or CSV row.
- `IngestionResult`: Stores the output of document ingestion.
- `NumericSlots`: Stores numerical information associated with a claim or evidence.
- `Claim`: Represents an extracted research claim.
- `NumericCheck`: Represents the result of numerical verification.

The schemas use Pydantic models to validate structured data and maintain consistency between processing stages.

### 5.2 Deterministic Source Anchors

**File:** `worker/ingestion/anchors.py`

Source anchors provide stable identifiers for extracted content.

Supported anchor types include:

- Paragraph anchors
- PDF table row anchors
- PDF table cell anchors
- CSV row anchors

The module also provides deterministic UUID generation.

This ensures that the same source content can be identified consistently across repeated processing runs, provided the source and anchor inputs remain unchanged.

### 5.3 CSV Ingestion

**File:** `worker/ingestion/csv_parser.py`

Responsible for reading CSV files and converting their contents into structured evidence chunks.

The implementation handles:

- CSV row extraction
- Header processing
- Duplicate headers
- Missing header values
- Ragged rows
- Empty rows
- Deterministic CSV row anchors

Each valid row is represented as an evidence chunk with its source information preserved.

### 5.4 PDF Ingestion

**File:** `worker/ingestion/pdf_parser.py`

Responsible for extracting research content from PDF documents using pdfplumber.

The parser handles:

- Paragraph extraction
- Table extraction
- Table row and cell information
- Page-level source tracking
- Table captions and headers
- Low-quality extraction indicators
- Detection of PDFs without extractable text

The current implementation targets text-based PDFs. Scanned documents requiring OCR are outside the current parser's supported scope.

### 5.5 Numeric Lexicon

**File:** `domain_packs/scientific_research/lexicon.py`

Defines domain-specific aliases and mappings used during numerical extraction.

Examples include:

| Category | Examples |
|---|---|
| Metrics | Accuracy, F1, precision, recall, AUC, RMSE, MAE |
| Entities | Our model, proposed method, proposed model |
| Periods | Training set, test set, validation set |
| Scales | K, thousand, M, million, B, billion |
| Units | ms, seconds, kg, mg, mL, km, Hz |

Metric aliases allow different expressions of the same metric to be mapped to a canonical representation.

### 5.6 Numeric Slot Extraction

**File:** `worker/extraction/slots.py`

Extracts structured numerical information from text.

The `NumericSlots` representation captures:

- Original numerical text
- Metric
- Entity
- Numerical value
- Unit
- Scale
- Period
- Comparison basis
- Denominator
- Decimal precision
- Approximation indicator
- Source anchor identifier

The implementation uses Python's `Decimal` type to avoid unnecessary floating-point precision errors.

It also handles multiple numerical mentions in a sentence and provides contextual information for downstream verification.

### 5.7 Claim Extraction

**File:** `worker/extraction/claims.py`

Identifies quantitative and comparative claims from paragraph chunks.

The implementation:

1. Processes paragraph chunks.
2. Splits paragraphs into individual sentences using spaCy.
3. Extracts numerical slots from each sentence.
4. Identifies comparison-related expressions.
5. Detects references to tables.
6. Classifies claims as quantitative or comparative.
7. Generates deterministic claim identifiers.
8. Preserves sentence offsets and source anchor references.

Examples of supported claim patterns:

- "The model achieved 95% accuracy."
- "Our method obtains an F1 score of 0.91."
- "Model A outperforms Model B by 3.4 points."
- "The performance increased by 3.2 percentage points."
- "The result is higher than the baseline by 2.1."

The current extractor uses a rule-based approach identified by:

`EXTRACTOR_VERSION = "rules-1"`

### 5.8 Evidence Slot Extraction

**File:** `worker/extraction/evidence_slots.py`

Extracts numerical information from evidence chunks so that it can be compared with the numerical information found in claims.

The module identifies numerical values and their associated context, including metrics, entities, periods, units and other available table or text context.

For table-like evidence, the current implementation uses the first column as the entity label and uses available headers or captions as metric, unit and period context. Tables with ambiguous or insufficient context may require review rather than being treated as confidently matched evidence.

### 5.9 Numeric Verification

**File:** `worker/verification/numeric.py`

Compares numerical claim slots with evidence slots.

The verification process considers:

- Numerical value
- Metric
- Entity
- Unit
- Scale
- Period
- Comparison basis
- Denominator
- Configured tolerance

The implementation uses `Decimal` for numerical comparisons and Pint for unit handling. It also accounts for written precision and approximate expressions when determining tolerance.

The output uses the `NumericCheck` schema.

Possible verification outcomes:

- `MATCH`
- `MISMATCH`
- `INCOMPARABLE`
- `NOT_APPLICABLE`

A result is not treated as a match merely because two numbers are equal: the relevant metric and contextual fields must also be sufficiently aligned.

### 5.10 Scientific Research Pack

**Directory:** `domain_packs/scientific_research/`

Provides domain-specific configuration and processing rules for scientific research documents.

It includes:

- Metric aliases and lexicon definitions
- Domain-specific metric handling
- Growth percentage calculations
- Percentage-point difference checks
- Scale-related hints
- Validation results and pack-level validation logic

This pack provides the scientific-research-specific layer used alongside the general ingestion, extraction and verification modules.

---

## 6. Installation and Setup

### Prerequisites

- Git and [uv](https://docs.astral.sh/uv/). If uv is not installed, install it with
  `python -m pip install uv`.
- Python 3.10 or later; Python 3.11 is used by the current development environment and Docker
  images.
- PostgreSQL 16 with pgvector, through Docker Compose or a local PostgreSQL installation that
  provides the pgvector extension.

### Create the environment

```bash
git clone <repository-url>
cd EvidenceGraph
uv sync --locked --python 3.11
```

`uv sync --locked` uses the exact dependency versions in `uv.lock` and installs the project and
development dependency groups. The explicit Python selector uses Python 3.11; the declared project
compatibility remains Python 3.10 and later.

### Configure the environment and database

```bash
cp .env.example .env
```

Edit `.env` for the local database and storage location. Set `DATABASE_URL` to the local PostgreSQL
address in this form, replacing every placeholder with local values:

```text
postgresql+psycopg://<local-user>:<local-password>@localhost:<port>/<database>
```

Do not put production credentials in this file or in the repository. Docker Compose's `postgres`
service uses the local development database configuration defined in `docker-compose.yml` and
creates its configured database on first startup. Start PostgreSQL and pgvector with:

```bash
docker compose up -d postgres
```

For native `uv run` commands, export values from `.env` in each shell before starting a process:

```bash
set -a
. ./.env
set +a
```

The API and worker must use the same `DATABASE_URL` and `STORAGE_ROOT`. The API and worker
containers share the configured uploaded-files volume. Compose reads `.env` automatically.

Apply database migrations before starting the API or worker:

```bash
uv run alembic upgrade head
```

The migration chain currently runs from `0001_persistence_foundation` through
`0005_one_companion_csv`. Revision `0002_dense_embeddings` enables pgvector and adds the nullable
384-dimensional embedding column.

### Start the API and worker

In one terminal, load `.env` as above and start the FastAPI application:

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port "${API_PORT:-8000}"
```

In a second terminal, load the same `.env` and start the background worker:

```bash
uv run python -m worker.main
```

The API accepts PDF and companion CSV uploads for an existing project. The worker polls queued
document rows, performs ingestion and verification, and persists run results. The API does not run
model inference during upload. `docker compose up --build -d` starts the configured PostgreSQL,
API, and worker services together.

### API and OpenAPI contract

- [`docs/api.md`](docs/api.md) documents document upload, processing-status read-back, verdict
  retrieval, error responses, and provenance fields.
- [`docs/openapi.json`](docs/openapi.json) is the checked-in OpenAPI description of the HTTP
  routes and schemas.

The principal routes are `POST /api/v1/projects/{project_id}/documents`,
`GET /api/v1/documents/{document_id}`, and
`GET /api/v1/analysis-runs/{run_id}/verdicts`. The API also exposes `/api/v1/health` and the
`/health` health-check alias.

---

## 7. Testing Strategy

Testing covers document-processing modules, platform adapters and persistence, API contracts,
worker orchestration, retrieval, and regression cases.

### Unit Testing

Tests individual modules independently.

Examples:

- Deterministic anchor generation
- CSV parsing and validation
- PDF paragraph and table extraction
- Claim extraction
- Numerical slot extraction
- Evidence slot extraction
- Numeric verification
- Scientific Research Pack validation

### Regression Testing

Ensures that previously supported numerical expressions continue to produce the expected structured output.

Examples:

- Percentage values
- Percentage-point differences
- Decimal values
- Scaled quantities
- Metric aliases
- Units
- Multiple numerical mentions
- Approximate values
- Comparison expressions

### Integration Testing

Integration tests exercise connected pipeline stages and PostgreSQL-backed retrieval. The complete
worker flow is also tested with deterministic data and mocked model inference. These tests do not
establish accuracy on representative real-world research documents.

Run the suite, Ruff, and the mypy targets used by CI with:

```bash
uv run python -m pytest
uv run ruff check .
uv run mypy eg_common persistence apps worker/orchestration worker/reporting worker/main.py
```

PostgreSQL retrieval integration tests use a dedicated migrated PostgreSQL/pgvector database. Set
`TEST_DATABASE_URL` to that test database and run:

```bash
uv run python -m pytest tests/integration/test_retrieval.py
```

If `TEST_DATABASE_URL` is unset outside CI, those database integration tests skip. In CI, the
integration fixture requires the variable.

---

## 8. Current Implementation Status

The integrated engineering path is implemented and covered by unit, integration, and mocked
end-to-end tests:

| Component | Current status |
|---|---|
| PDF and companion CSV intake, parsing and source anchors | Implemented; automated tests cover parser and ingestion behavior |
| PostgreSQL persistence and Alembic migrations 0001–0005 | Implemented; migration and repository tests are present |
| Background worker, retries and deterministic analysis runs | Implemented; worker and end-to-end tests are present |
| Claim extraction and numeric verification | Implemented and tested; detailed behavior is described in Section 5 |
| BM25, dense pgvector retrieval and reciprocal rank fusion | Implemented; unit and PostgreSQL integration coverage is present |
| Local CPU embeddings, NLI and reranking | Implemented with pinned model revisions; tests mock inference and do not download weights |
| Ordered policy and persisted verdict/provenance read-back | Implemented and tested; unset required thresholds produce Needs Review |
| FastAPI document intake, status and verdict endpoints | Implemented and tested; contracts are documented in `docs/api.md` |
| Evaluation on representative research documents | Not yet established; requires real-document data and evaluation |
| React frontend | Not present in this repository; remains a Member D responsibility |

The latest verified results recorded for the project are **218 passed** for the full test suite,
**3 passed** PostgreSQL retrieval integration tests, Ruff passed, and mypy passed for **37 source
files**. These are results from the latest verified run, not a guarantee that future runs will
pass.

The policy settings `POLICY_TAU_EXT`, `POLICY_TAU_RET`, `POLICY_TAU_E`, and `POLICY_TAU_C` remain
unset until Person D supplies development-set results and calibration. The backend implements the
ordered decision rules and abstention, but retrieval or verdict accuracy has not been established
on a representative real-world research dataset.

The PDF parser handles text-based PDFs. Scanned/image-only PDFs are reported as unsupported; OCR
is not implemented. Validation on representative real PDFs and CSVs, including inspection of
extracted claims and source locations, remains outstanding.

---

## 9. Design Considerations

The backend follows these principles:

**1. Traceability**

Every extracted claim and evidence chunk should retain a reference to its original source location.

**2. Determinism**

Anchor identifiers and claim identifiers should remain stable for identical inputs and processing versions.

**3. Structured Extraction**

Numerical information should be represented through structured schemas instead of remaining as unprocessed text.

**4. Numerical Precision**

The `Decimal` type is used for numerical values to reduce floating-point precision problems.

**5. Modular Architecture**

Ingestion, extraction, verification and domain-specific logic are maintained in separate modules.

**6. Testability**

Each component is designed to be independently testable and is also exercised through integrated
worker and API tests.

---

## 10. Integration with Other Members

The backend connects document parsers and extractors with persistence, retrieval, verification,
and API read-back. Document and analysis-run IDs are persisted; source anchors and chunk identity
remain attached to evidence through retrieval and verdict generation. Numeric values preserve
`Decimal` semantics in persistence and API serialization.

---

## 11. Future Work

Engineering integration is in place; the remaining project work is primarily evaluation and user
experience:

1. Person D supplies development and evaluation data, including annotated claims and the
   evaluation splits described in `EvidenceGraph_Framework.md`.
2. Person D evaluates extraction, retrieval, verification, verdict quality, abstention and
   calibration; those results are needed to set the four policy thresholds. Until then, they
   remain unset.
3. Person D implements the frontend against the API contracts in `docs/api.md` and
   `docs/openapi.json`.
4. Validate ingestion against representative real research PDFs and CSVs and inspect extracted
   claims, numeric slots, evidence, anchors and verdict explanations.
5. OCR for scanned PDFs remains outside the current implementation. Scanned/image-only PDFs
   cannot be processed by the current PDF parser.

---

## 12. Expected Outcome

The current backend accepts PDF and companion CSV documents, processes them asynchronously, and
persists claims, verification outputs, verdicts and source provenance. It provides a versioned
decision policy with abstention when evidence or calibrated thresholds are insufficient. Its
automated engineering tests do not substitute for evaluation on representative real research data.
