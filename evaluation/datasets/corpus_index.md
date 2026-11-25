# Corpus shortlist

Candidate article text comes from PLOS ONE under the Creative Commons
Attribution license. Check each companion dataset independently before copying
or redistributing it. Publisher table identifiers below are candidates for
manual PDF extraction. Corpus inclusion remains provisional until the text-based
PDF, tables and companion licenses have been checked.

| ID | Candidate | Tables to inspect | Proposed split |
|---|---|---|---|
| paper-001 | [Graph-based machine learning improves just-in-time defect prediction](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0284077) | 3 onward | train |
| paper-002 | [Predicting the number of defects in a new software version](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0229131) | 4, 6 | train |
| paper-003 | [Short text classification with machine learning in the social sciences](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0290762) | 2, 3 | train |
| paper-004 | [Classification of customer retention using hybrid SVC-SDNN](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0339995) | Performance comparison and class-specific metrics | train |
| paper-005 | [A localization strategy combined with transfer learning for image annotation](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0260758) | 2 | dev |
| paper-006 | [Comparison of hybrid classifiers for crop classification using NDVI](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0137748) | 5, 7, 8 | dev |
| paper-007 | [Multi-view classification with convolutional neural networks](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0245230) | 2 | dev |
| paper-008 | [Integrating temporal convolutional networks with metaheuristic optimization for defect prediction](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0319562) | Metrics by dataset | test candidate |
| paper-009 | [A global database of political administrative boundaries](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0231866) | Coverage and metrics. Check per-source license. | test candidate |
| paper-010 | [Notes on correctness of p-values when analyzing experiments using SAS and R](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0295066) | ANOVA result tables | test candidate |


## Source and licensing checks

The publisher's Copyright statement was checked for all ten article pages.
The companion files still need review. Paper 001 links an external repository,
paper 002 includes supporting information, paper 003 links a Zenodo deposit,
and paper 004 links third-party dataset copies. Paper 005 places the relevant
data in the manuscript. Paper 006 includes supporting files and paper 007
references external datasets. For paper 008 use the published article tables
unless licensing for the third-party data is established. Paper 009 links a
Dataverse release and paper 010 includes supporting information.

The first two training PDFs passed a parser probe. Reproduce the counts with
the downloaded PDFs identified by the hashes in the probe summary.

    python -m evaluation.datasets.probe evaluation/results/corpus-probe/paper-001.pdf evaluation/results/corpus-probe/paper-002.pdf

The probe measures extraction volume only. Accuracy requires independently
annotated claim spans and evidence anchors.

## External data review

The first corpus pass can use article text and published result tables as the
evidence bundle. This avoids relying on external companion data for those
documents. Keep separate PDF plus CSV fixtures for exercising CSV intake.

- Paper 001: the JiTReliability repository exposes the ZIP data, but its
  directory and README provide no explicit license. Use the article tables.
  [JiTReliability](https://github.com/lining-nwpu/JiTReliability)
- Paper 003: the authors distinguish the Apache-licensed code from a dehydrated
  deposit of post IDs. Use the article's aggregate tables and omit the raw
  social media records.
  [Author repository](https://github.com/shikarina/short_text_classification)
- Paper 007: PlantCLEF documents copyright-related exclusions for its task
  images. Use published metrics and exclude the external image datasets from
  this evidence bundle.
  [PlantCLEF data release](https://www.imageclef.org/node/198)
- External files for the other papers stay outside the first corpus pass.
  Record the per-file license and attribution before introducing a companion.

See [the open corpus pilot](open_corpus_pilot.md) for the external benchmarks.
Keep the SciTab and SEM-TAB-FACTS pilots separate from the project's published
paper train, dev, and sealed test splits.
