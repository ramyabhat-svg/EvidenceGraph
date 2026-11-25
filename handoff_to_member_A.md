# Handoff to Member A From Member D — EvidenceGraph

## 1. Frontend Project Structure

The layout below is the target structure Member A should expect when wiring CORS and environment variables.

```
apps/web/
├── src/
│   ├── api/
│   │   ├── client.ts          # base fetch wrapper, sets base URL, throws on non-2xx
│   │   ├── projects.ts        # typed functions for /projects endpoints
│   │   ├── documents.ts       # typed functions for /documents endpoints
│   │   ├── claims.ts          # typed functions for /claims endpoints
│   │   └── runs.ts            # typed functions for /runs endpoints
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
│   │   └── api.ts             # TypeScript interfaces auto-derived from Pydantic shapes
│   ├── App.tsx
│   └── main.tsx
├── public/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json              # strict: true
└── package.json
```

**TypeScript strict mode is on.** `tsconfig.json` must have `"strict": true`. All API response types in `src/types/api.ts` are derived directly from Member A's Pydantic response models. If A renames a Pydantic field, D's TypeScript breaks. This is intentional — it surfaces contract drift immediately.

**What A must do before Week 6:** expose stub endpoints that return fixture JSON in the correct shape so D can wire the API client as soon as the scaffold exists. The stubs can return hardcoded data; they just need the right field names and types.

---

## 2. React and TypeScript Implementation Status

| Component | Status | Target Week | Depends on A's endpoint |
|---|---|---|---|
| React + TypeScript + Vite + Tailwind scaffold | Not started | 6 | `GET /health` (smoke test) |
| `UploadPage` | Not started | 6–7 | `POST /projects/{id}/documents` |
| `DocumentList` | Not started | 6–7 | `GET /projects/{id}/documents` |
| `ClaimList` with status filter | Not started | 6–7 | `GET /documents/{id}/claims` |
| `ClaimDetail` with full trace | Not started | 6–7 | `GET /claims/{id}` |
| `ReviewForm` | Not started | 7 | `POST /claims/{id}/reviews` |
| `RunHistory` | Not started | 7 | `GET /projects/{id}/runs` |
| Typed API client (`src/api/`) | Not started | 6–7 | All endpoints |
| Frontend tests (Vitest + Testing Library) | Not started | 7–8 | Stub responses |

---

## 3. Required Backend API Endpoints

All endpoints are under the FastAPI app at `apps/api/`. URL prefix: `/api/v1`.

| # | Method | Path | Purpose | Available by |
|---|---|---|---|---|
| 1 | GET | `/health` | Health check + version | Week 1 |
| 2 | POST | `/projects` | Create a project | Week 2 |
| 3 | GET | `/projects` | List all projects | Week 2 |
| 4 | GET | `/projects/{project_id}` | Project detail | Week 2 |
| 5 | POST | `/projects/{project_id}/documents` | Upload PDF + optional CSV | Week 2 |
| 6 | GET | `/projects/{project_id}/documents` | List documents with status | Week 2 |
| 7 | GET | `/documents/{document_id}` | Document status + metadata | Week 2 |
| 8 | POST | `/documents/{document_id}/analyze` | Enqueue analysis run (see note below) | Week 3 |
| 9 | GET | `/documents/{document_id}/claims` | List claims; filterable | Week 3 |
| 10 | GET | `/claims/{claim_id}` | Full claim trace | Week 6 |
| 11 | POST | `/claims/{claim_id}/reviews` | Submit human review | Week 7 |
| 12 | GET | `/claims/{claim_id}/reviews` | Review history | Week 7 |
| 13 | GET | `/projects/{project_id}/runs` | List analysis runs | Week 6 |
| 14 | GET | `/runs/{run_id}` | Run detail + config | Week 6 |
| 15 | GET | `/runs/{run_id}/report` | Export report (JSON or HTML) | Week 7 |

**CORS:** `http://localhost:5173` must be in `allow_origins` during development. Configure in the FastAPI `CORSMiddleware` — do not hard-code it; read from `settings.cors_origins: list[str]`.

**Auth:** no user authentication in the MVP. Every endpoint is open. Add a note in `README` that this is intentional and not production-safe.

**File upload (endpoint 5):** `multipart/form-data`. Fields: `pdf_file` (required), `csv_file` (optional), `document_name` (optional string, display only). The server generates storage paths using `secrets.token_hex(16)`. Never construct paths from client-provided filenames — this is a path-traversal risk.

**Analysis auto-enqueue (endpoint 8):** Analysis is automatically enqueued when upload succeeds — the upload response returns `status: "queued"` and the worker picks it up. The `/analyze` endpoint exists as an explicit re-trigger (e.g., after a config change or a failed run), not as a required step in the normal upload flow. The frontend does **not** need to call `/analyze` after upload. This must be agreed in the Week 1 meeting and reflected in the worker orchestration code.

**Number of CSV files:** The MVP accepts one optional CSV per upload (`csv_file`). The Framework mentions "supporting CSVs" (plural) as a future capability. For now, enforce one CSV per document. Document this limit in the upload endpoint's OpenAPI description.

---

## 4. Shared Type Definitions

These are the canonical type strings used throughout. They must be identical in the Pydantic models, the DB enum columns, and the TypeScript interfaces. Agree these in the Week 1 `domain/schemas.py` meeting; do not change them unilaterally afterward.

### 4.1 `ClaimType` enum
```
quantitative | comparative | temporal | citation | categorical | other
```

### 4.2 `VerdictStatus` enum
```
Supported | Partially Supported | Contradicted | Unsupported | Needs Review | Processing Error
```

**Important:** `Processing Error` is a document-level status, not a claim-level verdict. It signals that a source could not be processed and no claims were extracted. It must **not** appear in the `?status=` filter on the claims list endpoint — that filter applies only to claims that exist. It appears only in the report summary counts and in document status. Enforce this in the Pydantic validator for the `status` query param: accept only the first five values.

### 4.3 `DocumentStatus` enum
```
queued | processing | complete | error
```

### 4.4 `NumericCheckResult` enum
```
match | mismatch | incomparable | not_applicable
```

### 4.5 `NLILabel` enum
```
entailment | contradiction | neutral
```

---

## 5. API Request and Response Shapes

All bodies are `application/json` except file upload (multipart). All datetimes are ISO 8601 UTC (`2026-02-10T14:00:00Z`). Numeric values that require exact decimal comparison use strings in JSON (e.g., `"91.2"` for 91.2% accuracy) — decide the canonical representation rule with B and C in the Week 1 meeting and apply consistently. The examples below follow the canonical rule: percentage values are stored in their display unit.

---

### 5.1 `GET /health`

**Response 200:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "db": "ok"
}
```

`db` is `"ok"` if the DB connection check passes, `"error"` otherwise. Used by Docker Compose `healthcheck`.

---

### 5.2 `POST /projects`

**Request:**
```json
{
  "name": "NeurIPS 2024 Audit",
  "description": "Checking numeric claims in submitted papers."
}
```

`description` is optional (nullable string).

**Response 201:**
```json
{
  "project_id": "proj-a1b2c3d4",
  "name": "NeurIPS 2024 Audit",
  "description": "Checking numeric claims in submitted papers.",
  "created_at": "2026-02-10T14:00:00Z",
  "document_count": 0
}
```

---

### 5.3 `GET /projects`

**Response 200:**
```json
{
  "projects": [
    {
      "project_id": "proj-a1b2c3d4",
      "name": "NeurIPS 2024 Audit",
      "description": "Checking numeric claims in submitted papers.",
      "created_at": "2026-02-10T14:00:00Z",
      "document_count": 3
    }
  ],
  "total": 1
}
```

---

### 5.4 `POST /projects/{project_id}/documents`

**Request:** `multipart/form-data`
- `pdf_file`: binary — required
- `csv_file`: binary — optional
- `document_name`: string — optional, display label only

**Response 202:**
```json
{
  "document_id": "doc-x9y8z7w6",
  "project_id": "proj-a1b2c3d4",
  "display_name": "paper_model_comparison.pdf",
  "pdf_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "csv_sha256": "a7f3c21984bde342f1a09c82345def67890abc123456789012345678901234567",
  "status": "queued",
  "created_at": "2026-02-10T14:01:00Z"
}
```

`csv_sha256` is `null` if no CSV was uploaded.

**Error 400 — invalid file type:**
```json
{
  "error": "invalid_file_type",
  "message": "Only .pdf files are accepted for pdf_file.",
  "field": "pdf_file"
}
```

**Error 413 — file too large:**
```json
{
  "error": "file_too_large",
  "message": "pdf_file exceeds the 50 MB size limit.",
  "field": "pdf_file"
}
```

**Error 422 — Pydantic validation (FastAPI default shape, do not override):** standard FastAPI 422 response is fine here.

---

### 5.5 `GET /documents/{document_id}` — Status polling

The UI polls this every 5 seconds until `status` is `complete` or `error`.

**Response 200 — in progress:**
```json
{
  "document_id": "doc-x9y8z7w6",
  "project_id": "proj-a1b2c3d4",
  "display_name": "paper_model_comparison.pdf",
  "pdf_sha256": "e3b0c44298fc1c...",
  "csv_sha256": "a7f3c21984bde3...",
  "status": "processing",
  "progress_stage": "extraction",
  "progress_message": "Extracting claims...",
  "progress_percent": 40,
  "page_count": 12,
  "updated_at": "2026-02-10T14:05:00Z",
  "error_message": null
}
```

**Response 200 — complete:**
```json
{
  "document_id": "doc-x9y8z7w6",
  "project_id": "proj-a1b2c3d4",
  "display_name": "paper_model_comparison.pdf",
  "pdf_sha256": "e3b0c44298fc1c...",
  "csv_sha256": "a7f3c21984bde3...",
  "status": "complete",
  "progress_stage": "done",
  "progress_message": "Analysis complete.",
  "progress_percent": 100,
  "page_count": 12,
  "claim_count": 14,
  "updated_at": "2026-02-10T14:15:00Z",
  "error_message": null
}
```

**Response 200 — error:**
```json
{
  "document_id": "doc-x9y8z7w6",
  "project_id": "proj-a1b2c3d4",
  "display_name": "paper_model_comparison.pdf",
  "pdf_sha256": "e3b0c44298fc1c...",
  "csv_sha256": null,
  "status": "error",
  "progress_stage": "ingestion",
  "progress_message": "Could not extract text from PDF. The file may be scanned.",
  "progress_percent": 5,
  "page_count": null,
  "claim_count": null,
  "updated_at": "2026-02-10T14:03:00Z",
  "error_message": "pdfplumber found 0 text characters on all pages. Scanned PDFs are not supported."
}
```

Valid `progress_stage` values (informational only, not an enum enforced by the client):
`queued | ingestion | chunking | extraction | retrieval | verification | policy | done | failed`

---

### 5.6 `GET /documents/{document_id}/claims`

**Query params:**
- `status` — optional; one of `Supported | Partially Supported | Contradicted | Unsupported | Needs Review`. Omit for all claims. **Do not accept `Processing Error` here** — that is not a claim verdict.
- `page` — integer ≥ 1, default 1
- `page_size` — integer 1–100, default 20

**Response 200:**
```json
{
  "document_id": "doc-x9y8z7w6",
  "total": 14,
  "page": 1,
  "page_size": 20,
  "claims": [
    {
      "claim_id": "clm-001",
      "claim_text": "Model A achieves 91.2% accuracy on the test set.",
      "claim_type": "quantitative",
      "verdict_status": "Supported",
      "source_anchor": {
        "page": 3,
        "element_type": "paragraph",
        "char_start": 142,
        "char_end": 198,
        "table_id": null,
        "row": null,
        "col": null
      },
      "extraction_confidence": 0.91,
      "extraction_method": "rule_v1"
    },
    {
      "claim_id": "clm-004",
      "claim_text": "The F1 score improved by 3.2 percentage points compared to the 2022 baseline.",
      "claim_type": "comparative",
      "verdict_status": "Contradicted",
      "source_anchor": {
        "page": 6,
        "element_type": "paragraph",
        "char_start": 88,
        "char_end": 157,
        "table_id": null,
        "row": null,
        "col": null
      },
      "extraction_confidence": 0.85,
      "extraction_method": "rule_v1"
    }
  ]
}
```

Note: `verdict_status` not `verdict` — using the compound name avoids shadowing the nested `verdict` object in the full claim detail response.

---

### 5.7 `GET /claims/{claim_id}` — Full Trace

This is the most join-heavy query in the system. Member A owns the trace query that joins `claims`, `source_locations`, `retrieval_candidates`, `verification_results`, `numeric_checks`, `verdicts`, and `review_events`. Return everything in one response — the UI does not make secondary requests.

**Response 200:**
```json
{
  "claim_id": "clm-001",
  "document_id": "doc-x9y8z7w6",
  "project_id": "proj-a1b2c3d4",
  "claim_text": "Model A achieves 91.2% accuracy on the test set.",
  "claim_type": "quantitative",
  "extraction_method": "rule_v1",
  "extraction_confidence": 0.91,
  "source_anchor": {
    "page": 3,
    "element_type": "paragraph",
    "char_start": 142,
    "char_end": 198,
    "table_id": null,
    "row": null,
    "col": null,
    "bounding_box": null
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
  "retrieved_evidence": [
    {
      "evidence_id": "evd-007",
      "evidence_text": "Model A: 91.2% (test set)",
      "source_anchor": {
        "page": 5,
        "element_type": "table_cell",
        "char_start": null,
        "char_end": null,
        "table_id": "table-3",
        "row": 2,
        "col": 3,
        "bounding_box": null
      },
      "retrieval_rank": 1,
      "bm25_score": 12.4,
      "dense_score": 0.87,
      "reranker_score": 0.93
    },
    {
      "evidence_id": "evd-012",
      "evidence_text": "Table 3: Results on test set. Model A achieves 91.2% accuracy.",
      "source_anchor": {
        "page": 5,
        "element_type": "table_caption",
        "char_start": 0,
        "char_end": 62,
        "table_id": "table-3",
        "row": null,
        "col": null,
        "bounding_box": null
      },
      "retrieval_rank": 2,
      "bm25_score": 9.1,
      "dense_score": 0.83,
      "reranker_score": 0.81
    }
  ],
  "nli_results": [
    {
      "evidence_id": "evd-007",
      "label": "entailment",
      "probabilities": {
        "entailment": 0.91,
        "contradiction": 0.04,
        "neutral": 0.05
      },
      "model_name": "cross-encoder/nli-deberta-v3-small",
      "model_revision": "abc123def456"
    }
  ],
  "numeric_checks": [
    {
      "evidence_id": "evd-007",
      "result": "match",
      "claim_slots": {
        "metric": "accuracy",
        "entity": "Model A",
        "value": "91.2",
        "unit": "%",
        "period": "test set"
      },
      "evidence_slots": {
        "metric": "accuracy",
        "entity": "Model A",
        "value": "91.2",
        "unit": "%",
        "period": "test set"
      },
      "tolerance": "0.05",
      "incomparable_reason": null,
      "trace": [
        "Claim value: 91.2 % (test set, Model A)",
        "Evidence value: 91.2 % (test set, Model A)",
        "Slots match: metric=accuracy, entity=Model A, period=test set",
        "Tolerance: ±0.05 (half of last reported decimal place in the % representation)",
        "Absolute difference: 0.0",
        "0.0 ≤ 0.05 → result: match"
      ]
    }
  ],
  "verdict": {
    "verdict_status": "Supported",
    "policy_rule_fired": 6,
    "abstention_reason": null,
    "policy_version": "v1.0",
    "run_id": "run-555aaa",
    "run_timestamp": "2026-02-10T14:15:00Z"
  },
  "review_history": []
}
```

**Key design decisions baked into this shape:**

- `retrieved_evidence` is an array — multiple evidence items are returned, each with its own scores.
- `nli_results` is an array keyed by `evidence_id` — NLI is run per claim–evidence pair, not once globally.
- `numeric_checks` is an array keyed by `evidence_id` — same reason. The decision policy picks the best result across all checks; the UI shows all of them.
- `numeric_slots` values are strings (`"91.2"`) to avoid float precision issues — this mirrors the `Decimal` usage in the backend. **Canonical representation rule (agree in Week 1 meeting):** percentage values are stored in their display unit (e.g., `"91.2"` with `unit: "%"`), not as a dimensionless ratio (`"0.912"`). Tolerance is calculated in the same canonical unit (e.g., `"0.05"` for a value reported to 1 decimal place in %).
- `tolerance` is also a string for the same reason.
- `bounding_box` is `null` for MVP (pdfplumber may not provide it); include the field now so the shape is stable when it is added.

---

### 5.8 `POST /claims/{claim_id}/reviews`

**Request:**
```json
{
  "reviewer_id": "member-d",
  "override_verdict": "Needs Review",
  "note": "Evidence cell may refer to a different model version. Flag for B to check the table header.",
  "flag_for_rerun": true
}
```

`override_verdict` must be one of the five claim-level `VerdictStatus` values (`Processing Error` is not valid here).
`note` is required (min length 1).

**Response 201:**
```json
{
  "review_id": "rev-012abc",
  "claim_id": "clm-001",
  "run_id": "run-555aaa",
  "reviewer_id": "member-d",
  "previous_verdict": "Supported",
  "override_verdict": "Needs Review",
  "note": "Evidence cell may refer to a different model version. Flag for B to check the table header.",
  "flag_for_rerun": true,
  "created_at": "2026-02-11T09:30:00Z"
}
```

**Behavior notes:**
- The system verdict in `verdicts` is never overwritten. Review events are appended to `review_events`.
- When `GET /claims/{claim_id}` is called after a review, `review_history` includes all past events. The UI shows the latest `override_verdict` as the effective human verdict (rendered differently from the system verdict badge).
- Write a `CLAIM_REVIEWED_BY` edge to `graph_edges` on every review submission (provenance requirement, Framework §3.7).

---

### 5.9 `GET /claims/{claim_id}/reviews`

**Response 200:**
```json
{
  "claim_id": "clm-001",
  "reviews": [
    {
      "review_id": "rev-012abc",
      "run_id": "run-555aaa",
      "reviewer_id": "member-d",
      "previous_verdict": "Supported",
      "override_verdict": "Needs Review",
      "note": "Evidence cell may refer to a different model version.",
      "flag_for_rerun": true,
      "created_at": "2026-02-11T09:30:00Z"
    }
  ],
  "total": 1
}
```

---

### 5.10 `GET /projects/{project_id}/runs`

**Query params:** `?page=1&page_size=20`

**Response 200:**
```json
{
  "project_id": "proj-a1b2c3d4",
  "total": 3,
  "page": 1,
  "page_size": 20,
  "runs": [
    {
      "run_id": "run-555aaa",
      "document_id": "doc-x9y8z7w6",
      "status": "complete",
      "started_at": "2026-02-10T14:02:00Z",
      "completed_at": "2026-02-10T14:15:00Z",
      "claim_count": 14,
      "error_count": 0,
      "policy_version": "v1.0",
      "nli_model": "cross-encoder/nli-deberta-v3-small@abc123def456",
      "embedding_model": "BAAI/bge-small-en-v1.5@def456ghi789",
      "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2@ghi789jkl012"
    }
  ]
}
```

Model version strings use `name@revision` format so a reviewer can pin-reproduce the exact run.

---

### 5.11 `GET /runs/{run_id}`

**Response 200:**
```json
{
  "run_id": "run-555aaa",
  "project_id": "proj-a1b2c3d4",
  "document_id": "doc-x9y8z7w6",
  "status": "complete",
  "started_at": "2026-02-10T14:02:00Z",
  "completed_at": "2026-02-10T14:15:00Z",
  "claim_count": 14,
  "error_count": 0,
  "configuration": {
    "policy_version": "v1.0",
    "nli_model": "cross-encoder/nli-deberta-v3-small@abc123def456",
    "embedding_model": "BAAI/bge-small-en-v1.5@def456ghi789",
    "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2@ghi789jkl012",
    "bm25_k": 10,
    "dense_k": 10,
    "reranker_top_k": 5,
    "tau_ext": 0.5,
    "tau_ret": 0.3,
    "tau_e": 0.8,
    "tau_c": 0.8
  },
  "input_hashes": {
    "pdf_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "csv_sha256": "a7f3c21984bde342f1a09c82345def67890abc123456789012345678901234567"
  }
}
```

`configuration` must persist exactly these fields from `analysis_runs`. Thresholds (τ values) come from the config file at run time and must be stored alongside model revisions so any run is reproducible.

---

### 5.12 `GET /runs/{run_id}/report?format=json`

`format` query param: `json` (default) or `html`.

**Response 200 (`format=json`):**
```json
{
  "report_id": "rpt-888xyz",
  "run_id": "run-555aaa",
  "project_id": "proj-a1b2c3d4",
  "document_id": "doc-x9y8z7w6",
  "generated_at": "2026-02-10T14:20:00Z",
  "pipeline_versions": {
    "policy_version": "v1.0",
    "nli_model": "cross-encoder/nli-deberta-v3-small@abc123def456",
    "embedding_model": "BAAI/bge-small-en-v1.5@def456ghi789",
    "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2@ghi789jkl012"
  },
  "input_hashes": {
    "pdf_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "csv_sha256": "a7f3c21984bde342f1a09c82345def67890abc123456789012345678901234567"
  },
  "summary": {
    "total_claims": 14,
    "Supported": 6,
    "Partially Supported": 1,
    "Contradicted": 2,
    "Unsupported": 3,
    "Needs Review": 2
  },
  "claims": [ "<<array of full claim trace objects as in §5.7>>" ],
  "limitations": "This report assesses claims against the supplied evidence only. It does not establish universal truth. Text-based PDFs only, English only."
}
```

Note: `Processing Error` is not in `summary` because it is a document-level state, not a claim verdict. The report only includes successfully extracted claims.

**Response 200 (`format=html`):** `Content-Type: text/html`. Static HTML document. All user-supplied text must be HTML-escaped server-side before insertion into the template. No inline scripts.

---

## 6. Claim, Evidence, and Verification-Result Display Requirements

Member A must ensure `GET /claims/{claim_id}` joins these tables in one query and returns all fields. Reference the DB tables from Framework §3.7.

| Field group | DB source table | Required API fields |
|---|---|---|
| Claim identity | `claims` | `claim_id`, `claim_text`, `claim_type`, `source_anchor.*` |
| Extraction metadata | `claims` | `extraction_method`, `extraction_confidence` |
| Numeric slots | `claims` (JSONB or columns) | `numeric_slots` is **`null`** for non-numeric claims (claim has no checkable numeric content). For numeric claims, it is a present object with individual slot fields nullable where the text does not establish them. Never return an all-null object for a non-numeric claim — use `null` at the top level. |
| Retrieved evidence | `retrieval_candidates` + `evidence_chunks` + `source_locations` | `evidence_id`, `evidence_text`, `source_anchor.*`, `retrieval_rank`, `bm25_score`, `dense_score`, `reranker_score` |
| NLI result | `verification_results` (type=nli) | `evidence_id`, `label`, `probabilities.*`, `model_name`, `model_revision` |
| Numeric check | `numeric_checks` | `evidence_id`, `result`, `claim_slots`, `evidence_slots`, `tolerance`, `incomparable_reason`, `trace` (array of strings) |
| Verdict | `verdicts` | `verdict_status`, `policy_rule_fired`, `abstention_reason`, `policy_version`, `run_id`, `run_timestamp` |
| Review history | `review_events` | all fields per review event |

**Escaping:** every text field from user input or document extraction (`claim_text`, `evidence_text`, `note`, `progress_message`, `error_message`) must be a plain string in JSON — no embedded HTML. The frontend React components escape on render via JSX. The API must not inject markup.

**The `numeric_slots` value field:** use a `str` (Decimal string) not a `float`. **Canonical representation:** store percentage values in their display unit — `"91.2"` with `unit: "%"`, not `"0.912"` with unit `"%"`. Tolerance is calculated in the same canonical unit: `"0.05"` (half of the last reported decimal place in %) not `"0.0005"`. This must be agreed with B in Week 1 and recorded in `domain/schemas.py`.

---

## 7. Human Review Functionality

### 7.1 Behavior contract

1. `POST /claims/{claim_id}/reviews` appends a row to `review_events`. It never modifies `verdicts`.
2. The response includes `previous_verdict` — read it from the most recent `verdicts` row for that claim at request time.
3. `GET /claims/{claim_id}` always returns the full `review_history` array, newest first.
4. The UI displays the system verdict and the latest human override as separate visual elements. This is a frontend concern, but the API must make it unambiguous by keeping them in separate fields (`verdict.verdict_status` vs `review_history[0].override_verdict`).
5. `flag_for_rerun: true` does not automatically trigger a new analysis run in the MVP — it just sets a flag. The UI can show a "flagged" badge on the claim. Actual re-run is manual.
6. Write a `CLAIM_REVIEWED_BY` graph edge to `graph_edges`:
   ```
   from_id:   claim_id
   to_id:     review_id
   edge_type: CLAIM_REVIEWED_BY
   run_id:    run_id of the verdict being reviewed
   ```

### 7.2 `review_events` table columns

```sql
review_id       TEXT PRIMARY KEY,
claim_id        TEXT NOT NULL REFERENCES claims(claim_id),
run_id          TEXT NOT NULL REFERENCES analysis_runs(run_id),
reviewer_id     TEXT NOT NULL,
previous_verdict TEXT NOT NULL,
override_verdict TEXT NOT NULL,
note            TEXT NOT NULL CHECK (length(note) >= 1),
flag_for_rerun  BOOLEAN NOT NULL DEFAULT FALSE,
created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

---

## 8. Evaluation Dataset — What A Must Support

Member D owns `evaluation/`. Member A does not touch those files. However, the evaluation harness calls the API to fetch predicted verdicts, so A must ensure:

### 8.1 Claim ID stability
When the evaluation harness runs the pipeline on an annotated document, the `claim_id` values assigned by the extraction step must be deterministic and stable across re-runs with the same input and config. Member D records these IDs during annotation import. If IDs change between runs, the harness cannot match predictions to ground-truth labels.

**Recommended approach:** derive `claim_id` from a stable hash:
```python
import hashlib
claim_id = "clm-" + hashlib.sha256(
    f"{document_id}:{source_anchor_page}:{char_start}:{char_end}".encode()
).hexdigest()[:12]
```
Agree the exact formula in the Week 1 meeting and document it in `domain/schemas.py`.

### 8.2 Batch evaluation support
The harness submits one document, polls for completion, then fetches all claims via `GET /documents/{id}/claims` (paginated). Member A must ensure:
- Pagination works correctly — `total` always reflects the true count, not just the current page.
- No artificial rate-limiting that would break a loop of ~150 `GET /claims/{id}` requests. In test/evaluation mode, disable any throttle middleware.

### 8.3 Import script for annotated claims
Member D will produce `evaluation/annotations/claims_annotated.jsonl`. A should provide (or AI-generate under A's review) a script at `evaluation/import_annotations.py` that reads this file and upserts records into a test DB so the harness can compare predictions. Schema mapping: `annotation.claim_id` → `claims.claim_id`, `annotation.verdict` → ground-truth label (stored in a separate `annotations` table, not in `verdicts`).

---

## 9. Annotation Schema — DB Alignment Requirements

Member D owns the annotation schema. Member A must ensure the DB schema accommodates it.

**Required DB support:**
1. `claims.numeric_slots` stored as `JSONB` (not individual columns) — the slot schema may evolve during Weeks 2–4, and JSONB avoids migration churn. Agree this in Week 1.
2. `source_locations` must store all of: `page`, `element_type`, `char_start`, `char_end`, `table_id`, `row`, `col`, `bounding_box`. All nullable except `page` and `element_type`.
3. A separate `annotations` table (not `verdicts`) for ground-truth labels:
   ```sql
   annotation_id   TEXT PRIMARY KEY,
   claim_id        TEXT NOT NULL REFERENCES claims(claim_id),
   split           TEXT NOT NULL CHECK (split IN ('train', 'dev', 'test')),
   verdict         TEXT NOT NULL,
   abstention_reason TEXT,
   annotator_id    TEXT NOT NULL,
   annotation_date DATE NOT NULL,
   notes           TEXT
   ```

---

## 10. Synthetic Benchmark — What A Must Support

Member D owns the synthetic generator. Member A must ensure:

1. File upload (endpoint 5) works for synthetic PDFs and CSVs generated programmatically — same validation rules apply.
2. No hardcoded assumption that a document comes from a real upload. The analysis pipeline must treat synthetic and real documents identically.
3. In evaluation mode (`EVIDENCEGRAPH_ENV=evaluation` env var), disable any per-document rate limiting so the harness can submit 50–100 documents in a loop without being throttled.

---

## 11. Evaluation Metrics — Fields the Harness Reads

Member D's harness calls `GET /claims/{claim_id}` for each claim and extracts these fields. Every field listed here must be present and non-null for a completed claim.

| What the harness needs | JSON path | Used for |
|---|---|---|
| Predicted verdict | `verdict.verdict_status` | Classification metrics (P/R/F1) |
| Policy rule fired | `verdict.policy_rule_fired` | Ablation analysis (which rule dominates) |
| Abstention flag | `verdict.verdict_status == "Needs Review"` | Abstention rate, risk-coverage curve |
| NLI label | `nli_results[0].label` | NLI-only baseline comparison |
| NLI entailment prob | `nli_results[0].probabilities.entailment` | Calibration analysis (Brier score) |
| Best numeric check result | `numeric_checks[0].result` | Numeric verifier ablation |
| Retrieval rank of top evidence | `retrieved_evidence[0].retrieval_rank` | Recall@k |
| Evidence source anchor | `retrieved_evidence[0].source_anchor` | Source-anchor accuracy |
| Run config (model revisions, policy version) | `verdict.policy_version`, `verdict.run_id` then `GET /runs/{run_id}` | Reproducibility checks |

The harness reads `nli_results[0]` and `numeric_checks[0]` (rank-1 evidence). If there are multiple, they are still useful for error analysis but the primary metrics use rank-1.

---

## 12. Frontend Dependencies and Configuration

### 12.1 Tech stack (to be pinned in Week 6)

| Package | Version range | Purpose |
|---|---|---|
| `react` | `^18.3.0` | UI framework |
| `react-dom` | `^18.3.0` | DOM renderer |
| `typescript` | `^5.4.0` | Type safety |
| `vite` | `^5.2.0` | Build tool and dev server |
| `tailwindcss` | `^3.4.0` | Utility CSS |
| `react-router-dom` | `^6.23.0` | Client-side routing |
| `vitest` | `^1.6.0` | Unit test runner |
| `@testing-library/react` | `^15.0.0` | Component tests |

No external UI component library. No React Flow or D3 in the MVP. Pin exact versions in `package.json` (`"react": "18.3.1"` not `"^18.3.1"`) before the first commit.

### 12.2 Dev server and API port

Vite dev server: `localhost:5173`. FastAPI: `localhost:8000`. Member A must add to `apps/api/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # read from config, not hard-coded
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

In `.env.example`:
```env
# API settings
CORS_ORIGINS=http://localhost:5173
DATABASE_URL=postgresql://evidencegraph:evidencegraph@localhost:5432/evidencegraph
API_PORT=8000

# Frontend settings (prefix VITE_ for Vite env injection)
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

### 12.3 Typed API client pattern (Member D's implementation reference)

```typescript
// src/api/client.ts
const BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    // Do NOT set Content-Type here for the base wrapper.
    // JSON requests set it explicitly per-call (see below).
    // Multipart/form-data uploads must NOT set Content-Type —
    // the browser sets it automatically including the boundary parameter.
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.error ?? "unknown_error", body.message ?? "");
  }
  return res.json() as Promise<T>;
}

// For JSON requests, pass the header explicitly:
// apiFetch("/claims/clm-001/reviews", {
//   method: "POST",
//   headers: { "Content-Type": "application/json" },
//   body: JSON.stringify(payload),
// })

// For multipart uploads, use FormData and pass NO Content-Type header:
// const fd = new FormData();
// fd.append("pdf_file", pdfFile);
// fd.append("csv_file", csvFile);
// apiFetch(`/projects/${projectId}/documents`, { method: "POST", body: fd })
// The browser automatically sets: Content-Type: multipart/form-data; boundary=----...

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

// src/api/claims.ts
import type { ClaimDetail, ClaimListResponse } from "../types/api";

export const getClaim = (claimId: string) =>
  apiFetch<ClaimDetail>(`/claims/${claimId}`);

export const getClaimList = (documentId: string, params: { status?: string; page?: number; page_size?: number }) => {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))
  );
  return apiFetch<ClaimListResponse>(`/documents/${documentId}/claims?${qs}`);
};
```

Member A's Pydantic models are the source of truth. If a field is renamed in Pydantic, update the TypeScript `src/types/api.ts` in the same PR.

---

## 13. Stub Endpoints (Week 2 requirement)

Before real pipeline modules are wired (Weeks 3–6), Member A must provide stubs for all endpoints that return valid fixture data in the correct shape. This lets Member D build and test the frontend against real response structures without waiting for the full pipeline.

A stub is a FastAPI route that returns a hardcoded Pydantic model instance. Example:

```python
# apps/api/routers/claims.py
@router.get("/claims/{claim_id}", response_model=ClaimDetailResponse)
async def get_claim(claim_id: str) -> ClaimDetailResponse:
    if settings.stub_mode:
        return FIXTURE_CLAIM_DETAIL  # hardcoded Pydantic instance
    return await db_service.get_claim_trace(claim_id)
```

Controlled by `STUB_MODE=true` in `.env`. Remove or gate stubs before the Week 6 E2E milestone.

---

## 14. Consistent Error Response Shape

All error responses across all endpoints must use this shape. Member A should implement a FastAPI exception handler for `ApiError` and for unhandled exceptions (return 500 with a generic message, no stack traces).

```json
{
  "error": "snake_case_error_code",
  "message": "Human-readable explanation safe to show in the UI.",
  "field": "affected_field_name_or_null"
}
```

Common error codes:

| HTTP status | `error` code | When |
|---|---|---|
| 400 | `invalid_file_type` | Wrong extension or file signature |
| 400 | `invalid_verdict` | `override_verdict` not in allowed set |
| 400 | `invalid_status_filter` | `?status=Processing Error` on claims endpoint |
| 404 | `not_found` | Resource does not exist |
| 409 | `duplicate_document` | Same SHA-256 already exists in this project |
| 413 | `file_too_large` | Exceeds size limit |
| 422 | (FastAPI default) | Pydantic validation failure — leave as-is |
| 500 | `internal_error` | Unhandled server error |

---

## 15. Priority Order: What D Needs From A

| Priority | Deliverable | Needed by (week start) |
|---|---|---|
| P0 | `GET /health` live, CORS configured for `localhost:5173` | Week 2 |
| P0 | `POST /projects/{id}/documents` returning `document_id` and `status: queued` | Week 2 |
| P0 | `GET /documents/{id}` with status polling fields | Week 2 |
| P1 | All stub endpoints returning fixture data in correct shape | Week 3 |
| P1 | `GET /documents/{id}/claims` with pagination and status filter | Week 3 |
| P1 | Claim ID stability guarantee (hash formula agreed and documented) | Week 3 |
| P2 | `GET /claims/{id}` full trace (real data from pipeline) | Week 6 |
| P2 | `GET /projects/{id}/runs` and `GET /runs/{id}` | Week 6 |
| P3 | `POST /claims/{id}/reviews` and `GET /claims/{id}/reviews` | Week 7 |
| P3 | `GET /runs/{id}/report?format=json` and `format=html` | Week 7 |
| P3 | Annotation import script (`evaluation/import_annotations.py`) | Week 7 |

---

## 16. Contract Stability Rules

1. Field names and types agreed in the Week 1 meeting are frozen. Changes go through: open GitHub issue → discuss in weekly sync → update `domain/schemas.py` by hand → A regenerates dependent code with AI under A's review.
2. New optional nullable fields are additive and non-breaking. A can add them without a sync. D will absorb them transparently in TypeScript.
3. The `VerdictStatus`, `ClaimType`, `DocumentStatus`, `NumericCheckResult`, and `NLILabel` enum string values are frozen from Week 1. New values require a full team decision because they affect ground-truth annotation labels, UI badges, harness logic, and DB enum columns simultaneously.
4. The `claim_id` hash formula is frozen after Week 1. Any change invalidates the annotated dataset.
