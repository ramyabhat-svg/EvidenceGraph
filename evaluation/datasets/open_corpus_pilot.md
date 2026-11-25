# Open scientific claim verification pilot

## Corpus decision

Use SciTab as an external dev benchmark for quantitative verification. The
release contains 1,224 rows and publishes versioned arXiv IDs, table IDs,
captions, table content, and human-verified labels. The authors describe
two-round verification with different annotators and author adjudication.
The repository has an MIT license. Keep original article PDFs local to source
checks and verify each article's reuse terms before redistributing it.

- [Released SciTab dataset](https://github.com/XinyuanLu00/SciTab/blob/main/dataset/sci_tab.json)
- [SciTab license](https://github.com/XinyuanLu00/SciTab/blob/main/LICENSE)
- [SciTab methods, especially sections 2.1 through 2.3](https://aclanthology.org/2023.emnlp-main.483.pdf)

The paper describes generated counterclaims. The primary pilot therefore
uses 12 supported numerical statements from distinct papers and excludes
explicit continuation fragments. These cases are useful for a first
alignment check. A supported-only sample cannot measure false positives or
calibrate a multiclass verdict policy. Keep external benchmark labels separate
from EvidenceGraph's adjudicated document-level labels.

Use SEM-TAB-FACTS dev as a secondary alignment check for table cells. The
organizers license the data CC BY 4.0, and the dev output XML marks relevant
cells. The natural-statement index indexes manual training examples and has
no document-ID overlap with the official dev XML. The six dev cases therefore
retain their published labels and cell coordinates without claiming that
their wording is verbatim from an article. SciFact is useful for text-only
verification and is excluded from this table-evidence pilot.

- [SEM-TAB-FACTS organizers and data license](https://sites.google.com/view/sem-tab-facts)
- [Official dev v1.1 archive](https://drive.google.com/file/d/1l5iojO8q_CB-sDCjlUpa7wVi8XUrqlss/view)
- [Natural-statement index](https://drive.google.com/file/d/1635tOXOACfJVybg1s6NbHWFpXU6x48f-/view)
- [SciFact paper](https://arxiv.org/abs/2004.14974)

## Files and checkpoint

- scitab/dev-pilot.jsonl contains the 12 source-linked SciTab examples with
  the released benchmark label and any original PDF checks. Source
  sci_tab.json SHA-256 is
  883843572567e6e2457870c349be83dfc2392fe4d13d89317d06ccf908d21573.
- semtabfacts/dev-cell-pilot.jsonl contains six auxiliary cell-anchored dev
  cases. Source dev_v1.1.zip SHA-256 is
  44a5f0dc120a5c3610a8f6795f400b425bfd795be6d47fd7a8c72a02904ffb03.
- No project test data was opened. The other eight SciTab PDFs were not
  needed for the initial check, and not every pilot claim has an anchor
  established in the original PDF.

The original PDF for arXiv 1902.06423v1 is the most useful first review.
The unchanged statement and its table caption were both located on physical
page 7. The local B extractor did not emit an exact normalized sentence
match. Across the four PDFs checked, none of the selected statements was an
exact emitted claim. Keep these misses visible and do not use the benchmark
UUIDs as application claim UUIDs or turn a related sentence into a match.
A printed table number also differs from the parser's table index. Review
the relevant row/cell and confirm the persisted anchor before scoring.
[First source PDF](https://arxiv.org/pdf/1902.06423v1)

For the end-to-end study, keep the existing openly licensed published-paper
corpus proposal. Have two humans independently verify the wording, verdict
and physical evidence anchors of the selected document claims. Imported
SciTab labels provide an external reference and do not replace that review.
Keep each source paper and version family in one project split.

When one engineering run is available, record its PDF hash and use the actual
persisted claim and document UUIDs to write the adjudicated dev JSONL. The
checkpoint command expects each row to carry the document UUID, EvidenceGraph
verdict, adjudicated flag, and expected evidence anchors. Supply C's stage
input JSONL with the run UUID on each row. Missing exact UUIDs, missing stage
inputs, and incomplete anchor matches are reported independently.

    python -m evaluation.dev_checkpoint --annotations path/to/dev-reviewed.jsonl --verdicts path/to/native-verdicts.json --policy-inputs path/to/dev-policy-inputs.jsonl --output evaluation/results/dev-checkpoint.json

The archive provides verdicts and provenance, but its API omits the complete
policy-input export. A live C run and independent review in EvidenceGraph
remain pending. The Docker daemon was unavailable at the time of the probe.

