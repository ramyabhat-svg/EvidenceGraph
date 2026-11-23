# Requests for Member D

Please confirm these integration decisions against the frontend and evaluation contracts:

1. Claim IDs are document-scoped UUID strings derived from
   `(document_id, source_anchor_id, char_start, char_end)`, rather than the illustrative
   `clm-` plus SHA-256 string. This remains stable across runs.
2. A claim's `numeric_slots` trace field is an array of slot objects, matching Member B's list, or
   null for non-numeric claims; it is not one slot object.
3. The API passes Member B's numeric values and unit tokens verbatim (for example, unit `percent`
   and ratio values). The handoff's canonical-percent rule needs a decision with Member B.
4. Source anchors map `kind` to `element_type`, `table_index` to a `table-N` `table_id`, `bbox` to
   `bounding_box`, and CSV row `page` to null.
5. Document status is `queued|processing|complete|error`, replacing the Technical Specification's
   `ProcessingStatus` values.
6. `Processing Error` is document-level only. The handoff contradicts itself between sections 4.2
   and 5.12 about its use as a claim verdict.
7. The annotation import script will live in `scripts/` unless you prefer another A-owned path;
   the handoff's `evaluation/import_annotations.py` location is D-owned.
8. A completed claim may have no `nli_results[0]` or `numeric_checks[0]` for non-numeric claims or
   while NLI is still a C-owned stub.
9. The MVP accepts one optional CSV per PDF upload.
10. The API document means one PDF plus its optional companion CSV; persistence stores one row per
    file, with the CSV linked to the PDF.
