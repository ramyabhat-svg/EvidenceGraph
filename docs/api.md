# Document API contracts

All routes use the `/api/v1` prefix. The MVP has no authentication. Expected errors use
`{"error": "<snake_case_code>", "message": "<safe text>", "field": <name or null>}`;
FastAPI request-validation errors retain the default 422 response.

## Upload a document

`POST /api/v1/projects/{project_id}/documents`

Send `multipart/form-data` with a required `file` part. The filename extension must be `.pdf` or
`.csv`; PDF content must have a PDF header and CSV content must be valid UTF-8. Upload size is
limited by `MAX_PDF_MB` or `MAX_CSV_MB`. CSV intake also requires a `parent_document_id` form field
that identifies a PDF in the same project. PDF uploads must omit that field. The referenced project
must already exist.

Successful intake returns **202 Accepted**:

```json
{
  "document_id": "<uuid>",
  "file_document_id": "<uuid>",
  "project_id": "<uuid>",
  "file_type": "pdf",
  "status": "queued",
  "parent_document_id": null
}
```

`document_id` identifies the API document (the PDF row); `file_document_id` identifies the uploaded
file row. They are the same for a PDF upload. For a CSV upload, `document_id` is its required
parent PDF and `file_document_id` is the new companion CSV row. A PDF can have at most one CSV.

The API stores bytes under `STORAGE_ROOT/{project_id}/{file_document_id}.{pdf|csv}`. It writes to a
temporary sibling, then atomically renames to the final path before committing the queued document
row. API and worker share this configured directory (a named volume in Compose). The worker alone
performs parsing and model inference.

Upload errors include `invalid_file_type` (400), `invalid_file_content` (400),
`parent_document_required` (400), `invalid_parent_document` (400), `file_too_large` (413),
`not_found` for a missing project (404), `duplicate_document` for a repeated PDF in the project
(409), `companion_csv_exists` when the PDF already has a CSV (409), and `storage_unavailable`
(503). A failed database write removes the uncommitted stored file.

## Read processing status

`GET /api/v1/documents/{document_id}` returns **200 OK**:

```json
{
  "document_id": "<uuid>",
  "project_id": "<uuid>",
  "status": "queued",
  "processing_error": null,
  "analysis_run_ids": [],
  "files": [
    {
      "file_document_id": "<uuid>",
      "file_type": "pdf",
      "status": "queued",
      "processing_error": null
    }
  ]
}
```

The document status aggregates its PDF and companion CSV: `error` if any file failed, otherwise
`processing` if any file is processing, otherwise `queued` if any file is queued, otherwise
`complete`. `processing_error` is the first failed file's safe error code or null. `files` contains
each file row's own status. The route accepts either the API document ID or a companion file ID and
normalizes to the parent PDF. `analysis_run_ids` is empty until a run is persisted. Missing
documents return the shared 404 error body.

## Read verdicts and provenance

`GET /api/v1/analysis-runs/{run_id}/verdicts` returns **200 OK** with the document ID and one item
per persisted claim verdict. Each item includes the claim ID, policy status, confidence, reason,
explanation, policy version, numeric slot results and checks, NLI class distributions, reranker
scores, and evidence provenance. Provenance includes persisted and source chunk IDs, document ID,
anchor ID, anchor kind, page/table/row/column or character offsets, and source quality flags. The
response does not include source document text.

Numeric `tolerance`, `difference`, and decimal slot values are JSON strings to preserve exact
`Decimal` values. NLI distributions and reranker values are numeric scores as persisted. If no
verdicts exist yet, the run response contains an empty list. A missing run returns the shared 404
error body. Unset policy calibration thresholds remain unset; such runs may contain `Needs Review`
verdicts and are returned without alteration.
