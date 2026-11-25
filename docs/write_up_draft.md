# EvidenceGraph study draft

## Research question

Can a scientific claim verification workflow surface reliable numeric evidence
and abstain when reported results lack comparable context? Evaluate the effect of
dense retrieval, reranking, table context, numeric validation, and abstention
with controlled ablations.

## Methods

EvidenceGraph extracts claims and structured numeric slots from text PDFs and
indexes PDF and optional CSV evidence with source locations. The application
preserves candidate sources and validation steps, and records subsequent human
reviews separately from each system run. Use document-level splits and stable
claim IDs to join labels with predictions. Record misses when a human-annotated
claim cannot be matched and publish coverage alongside metrics.

Compare BM25 with NLI, hybrid retrieval with NLI, and hybrid retrieval plus
reranking with NLI. Compare the full numeric-aware configuration against
ablations that remove dense retrieval, reranking, table context or abstention.
Choose thresholds on development data with C and record policy and model
versions and hashes for the final run. Compute per-verdict and macro F1,
document-bootstrap uncertainty, retrieval coverage, numeric mismatch metrics,
abstention, and NLI entailment calibration. Report denominators and missing
metrics explicitly.

## Related work and results

Related-work questions to check in the full papers include SciFact's evidence
selection, SciTab's use of scientific tables, FEVEROUS's joint text and table
evidence, and the numeric operations in FinQA and TAT-QA. D must verify full
texts and dataset licenses before adding these as citations.

The local smoke test confirms workflow behavior using a generated document.
Report study results after human annotation and the full C pipeline are ready.
Report the development and sealed-test results separately and retain
configuration and source hashes for each run.

## Limitations

The MVP accepts English text-based PDFs and one optional CSV. Extracted table
structure and the evidence bundle limit what can be checked. Calibration based
on NLI entailment probability assesses a specific signal and does not represent
calibration of the full system verdict.
