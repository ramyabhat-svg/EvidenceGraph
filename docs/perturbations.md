# Synthetic benchmark draft

The generator emits 10 controlled examples per type by default using seed 42.
It uses nine types because the detailed Week 3 table names nine. The Week 5
checklist says eight. Keeping all nine preserves the distinction between general
unit incompatibility and the percentage-point case until D and C agree on the
freeze. These controlled records do not derive from human-annotated papers.

| Type | Controlled change | Expected verdict | Rule |
|---|---|---|---|
| value_beyond_tolerance | Add 1.00 percentage point to a precisely reported result | Contradicted | 2 |
| value_within_tolerance | Round a two-decimal percentage to an integer | Supported | 6 |
| unit_scale_swap | Change milliseconds to seconds while keeping the digits | Contradicted | 2 |
| unit_incomparable | Replace milliseconds with kilograms | Needs Review | 3 |
| period_condition_swap | Change test to train | Needs Review | 3 |
| percent_vs_pp_swap | Replace percent with percentage points with no conversion basis | Needs Review | 3 |
| entity_swap | Replace the reported model with its control | Needs Review | 3 |
| evidence_removed | Remove the entire evidence record | Unsupported | 4 |
| low_quality_anchor | Mark the table cell low quality | Needs Review | 1 |

All unchanged evidence is supplied as a sentence and an illustrative table cell
anchor. For the removed-evidence case, both fields are null. The low-quality case
sets the anchor quality flag. The rounded case assumes comparable slots,
qualifying evidence, and tolerance based on the precision reported in the claim.
The policy verdicts in this table come from the Member D plan. Review the emitted
text, slot parsing, table context and rules before freezing a research benchmark.

Run from the workspace root.

    python -m evaluation.datasets.synthetic --seed 42 --per-type 10 --output evaluation/datasets/synthetic_benchmark.draft.jsonl

The test suite parses the entire 90-record draft with Member B's slot extractor
and checks the eight types that include evidence against B's numeric verifier.
The low-quality case still matches numerically. The quality flag is an input to
C's verdict policy. The missing-evidence records have no numeric comparison.
This check exercises B's code and does not validate the expected C verdicts.

    python -m pytest -q evaluation/test_evaluation.py

## Policy replay

Decision policy v2 classifies a successfully completed search with no candidates
as Unsupported after the extraction and source-quality checks. A missing
reranker score for a nonempty search still yields Needs Review. New runs
record the empty-search flag alongside the other policy inputs.

The controlled replay now agrees with the draft for all nine perturbation
types, including the 10 removed-evidence cases. The benchmark remains a draft
pending review and a run with the retrieval and inference models.

    python -m evaluation.synthetic_policy_probe
