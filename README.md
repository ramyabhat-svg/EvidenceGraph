# EvidenceGraph — Member B: Document Ingestion, Claim Extraction & Numeric Verification

## 1. Overview

EvidenceGraph is an evidence-grounded research analysis system designed to extract claims from research documents, connect them to supporting evidence, and verify numerical information.

This repository contains **Member B's implementation**, which focuses on the document-processing and evidence-analysis pipeline.

The module is responsible for:

- Extracting structured content from PDF and CSV documents.
- Generating deterministic source anchors for traceability.
- Splitting research text into meaningful claims.
- Extracting numerical values and their associated metrics.
- Identifying evidence slots from supporting content.
- Verifying numerical claims against extracted evidence.
- Providing a Scientific Research Pack for domain-specific processing.

The objective is to ensure that extracted claims retain their connection to the original source, allowing downstream components to inspect and verify the evidence behind them.

---

## 2. Member B Responsibilities

Member B owns the following processing pipeline:

| Component | Responsibility |
|---|---|
| Document ingestion | Read and process PDF and CSV files |
| Source anchoring | Generate stable identifiers for paragraphs, table rows, cells and CSV rows |
| Claim extraction | Identify quantitative and comparative claims from research text |
| Numeric slot extraction | Extract metrics, values, units, entities and other numerical context |
| Evidence slot extraction | Extract corresponding numerical information from evidence chunks |
| Numeric verification | Compare claim values against supporting evidence |
| Scientific Research Pack | Provide domain-specific metric aliases, rules and configuration |

### Main processing flow

```text
              Research Document
                      |
                      v
              Document Ingestion
                 /         \
                v           v
           PDF Parser    CSV Parser
                \           /
                 v         v
                Evidence Chunks
                       |
             +---------+---------+
             |                   |
             v                   v
       Claim Extraction    Evidence Slot Extraction
             |                   |
             v                   v
       Numeric Slots       Evidence Slots
             |                   |
             +---------+---------+
                       |
                       v
              Numeric Verification
                       |
                       v
             Verification Results
```

---

## 3. Project Structure

The following structure represents the Member B implementation and its associated tests.

```text
evidencegraph/
│
├── domain/
│   └── schemas.py
│
├── worker/
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── anchors.py
│   │   ├── pdf_parser.py
│   │   └── csv_parser.py
│   │
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── claims.py
│   │   ├── slots.py
│   │   └── evidence_slots.py
│   │
│   └── verification/
│       └── numeric.py
│
├── domain_packs/
│   └── scientific_research/
│       ├── lexicon.py
│       └── pack.py
│
├── tests/
│   │
│   ├── fixtures/
│   │
│   ├── unit/
│   │   ├── test_anchors.py
│   │   ├── test_csv_parser.py
│   │   ├── test_pdf_parser.py
│   │   ├── test_claims.py
│   │   ├── test_evidence_slots.py
│   │   ├── test_numeric.py
│   │   └── test_pack.py
│   │
│   └── regression/
│       ├── test_slots_golden.py
│       └── test_numeric_golden.py
│
├── config/
│   └── numeric.yaml
│
├── scripts/
│   └── pdf_spike.py
│
├── requirements.txt
└── pytest.ini
```

Some files and tests are still planned and will be added as implementation progresses.

---

## 4. Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.10.11 | Primary implementation language |
| Pydantic v2 | Data models and validation |
| pdfplumber | PDF text and table extraction |
| spaCy | Sentence segmentation and NLP preprocessing |
| Decimal | Precise numerical representation |
| Pint | Unit handling and comparison |
| PyYAML | Configuration management |
| pytest | Unit and regression testing |

---

## 5. Core Implementation Modules

### 5.1 Shared Domain Schemas

**File:** `domain/schemas.py`

Defines the structured data contracts used throughout the Member B pipeline.

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

Planned module for extracting numerical information from evidence chunks.

It will identify the numerical values and associated context needed to compare evidence against extracted claims.

### 5.9 Numeric Verification

**File:** `worker/verification/numeric.py`

Planned module for comparing numerical claim slots with evidence slots.

The verification process will consider:

- Numerical value
- Metric
- Unit
- Scale
- Period
- Comparison basis
- Denominator
- Configured tolerance

The output will use the `NumericCheck` schema.

Possible verification outcomes:

- `MATCH`
- `MISMATCH`
- `INCOMPARABLE`
- `NOT_APPLICABLE`

### 5.10 Scientific Research Pack

**Directory:** `domain_packs/scientific_research/`

Provides domain-specific configuration and processing rules for scientific research documents.

It will integrate the numerical lexicon, metric definitions, unit handling and domain-specific validation settings.

---

## 6. Installation and Setup

### Prerequisites

- Python 3.10.11
- pip
- Git
- Visual Studio Code (recommended)

### Step 1: Clone the repository

```cmd
git clone <repository-url>
cd evidencegraph
```

### Step 2: Create a virtual environment

```cmd
python -m venv .venv
```

### Step 3: Activate the virtual environment

For Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

### Step 4: Install dependencies

```cmd
python -m pip install -r requirements.txt
```

### Step 5: Download the spaCy English model

```cmd
python -m spacy download en_core_web_sm
```

The claim extraction module also supports a blank English spaCy pipeline with sentence segmentation as a fallback when the trained model is unavailable.

### Step 6: Run tests

Run the complete test suite:

```cmd
pytest -v
```

Run only unit tests:

```cmd
pytest tests\unit -v
```

Run regression tests:

```cmd
pytest tests\regression -v
```

---

## 7. Testing Strategy

Testing is performed at multiple levels.

### Unit Testing

Tests individual modules independently.

Examples:

- Deterministic anchor generation
- CSV parsing and validation
- PDF paragraph and table extraction
- Claim extraction
- Numerical slot extraction
- Numeric verification

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

Will validate the complete processing flow from document ingestion to claim extraction, evidence extraction and numerical verification.

---

## 8. Current Implementation Status

<text>Progress as of 8 November 2026.</text>

| Stage | Component | Status |
|---|---|---|
| 0 | Environment and project setup | Completed |
| 1 | Pydantic schemas | Implemented; dedicated schema tests not yet confirmed |
| 2 | Deterministic anchors | Completed and tested |
| 3 | CSV ingestion | Completed; 7 tests passed |
| 4 | PDF ingestion | Implemented; 6 mocked/unit tests passed |
| 5A | Scientific research lexicon | Completed; 6 tests passed |
| 5B | Numeric slot extraction | Implemented; regression tests passed |
| 6 | Claim extraction | Implementation and tests supplied; execution pending |
| 7 | Evidence slot extraction | Pending |
| 8 | Numeric verification | Pending |
| 9 | Scientific Research Pack | Pending |
| 10 | Integration and end-to-end testing | Pending |

**Important testing note:** The PDF parser has passed mocked unit tests, but validation against a collection of real research PDFs is still required.

---

## 9. Design Considerations

The Member B implementation follows these principles:

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

Each component is designed to be independently testable before integration.

---

## 10. Integration with Other Members

Member B's modules are designed to integrate with the platform architecture maintained by Member A.

The processing pipeline consumes document-level inputs and produces structured outputs that can be persisted and used by downstream components.

Expected integration data includes:

- `document_id`
- `file_hash`
- `file_type`
- Evidence chunks
- Extracted claims
- Numeric slots
- Evidence slots
- Numeric verification results

The shared schemas and function signatures should remain aligned with the contracts agreed upon by the team.

Database persistence, API endpoints, job orchestration and deployment are handled by the platform/integration responsibilities rather than independently duplicated in this module.

---

## 11. Future Work

The remaining implementation work includes:

1. Complete claim extraction testing and refine extraction behaviour where required.
2. Implement evidence slot extraction.
3. Implement numerical claim-to-evidence verification.
4. Complete the Scientific Research Pack.
5. Validate PDF extraction on real scientific research documents.
6. Add integration tests for the complete Member B pipeline.
7. Coordinate shared schema and API integration with Member A.
8. Evaluate extraction quality using representative research documents and a manually annotated test set.

---

## 12. Expected Outcome

At completion, the Member B pipeline will convert research documents into traceable, structured claims and evidence.

It will support the extraction of numerical information from research text and evidence tables, preserve source references, and provide a systematic mechanism for checking whether numerical claims are supported by the available evidence.

This module forms the document-processing, claim-extraction and numerical-verification foundation of EvidenceGraph.

---

**Module
