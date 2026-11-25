# Evaluation

Run the controlled A/B demo and evaluate its exported trace.

    python -m evaluation.demo

The CLI accepts one JSON report per analyzed document. Use complete reports for
the selected papers so extraction precision has the correct denominator.
Each real report must record its exact experiment config as
`experiment_config`. The Phase 0 API cannot apply these configurations.
The eight JSON configs define the experiment matrix for the C integration.

    python -m evaluation.run_eval --experiment full_system --split dev --annotations path/to/dev.jsonl --report path/to/report.json --output evaluation/results/full_system_dev.json

Use `--allow-fallback` only for smoke reports. The scorer records input hashes and
uses null for unavailable rates. Macro F1 averages labels represented in gold
or predictions. Classification runs on matched claims. For extraction, missing
and extra predictions affect recall and precision respectively.

Generate dev retrieval queries from human-labeled train/dev data.

    python -m evaluation.datasets.builder path/to/train_dev.jsonl evaluation/datasets/retrieval_eval.jsonl

The perturbation generator uses controlled fixtures. See the draft spec before
using them. Real annotation, independent labeling, and final evaluation remain
separate steps in the study protocol.

Compute agreement on two independently labeled files. Each file should contain
one record per claim and both should cover the same subset.

    python -m evaluation.annotations.agreement path/to/first.jsonl path/to/second.jsonl

## Engineering backend snapshots

After a document is complete, read its `analysis_run_ids` from
`GET /api/v1/documents/{document_id}`. Save
`GET /api/v1/analysis-runs/{run_id}/verdicts` to a JSON file. Use the actual
claim UUIDs from that backend in the human annotations.

    python -m evaluation.run_eval --experiment full_system --split dev --annotations path/to/dev.jsonl --report path/to/native-verdicts.json --engineering-verdicts --output evaluation/results/engineering-dev-diagnostics.json

Repeat the report option across distinct documents in the dev split. This mode
reports reranked evidence using the persisted reranker scores. Tied scores are
ordered by evidence UUID. The native response has no original retrieval ranks
or attested experiment configuration. The scorer therefore reports diagnostics
and does not accept these snapshots for ablations or final test scoring.

## Dev threshold calibration

The calibrator replays C's archived ordered policy against human dev labels.
It selects a candidate by macro F1, then by coverage, and uses the lowest
threshold tuple to break ties. The result includes the four thresholds and
hashes of the data and candidate grid. Approve the candidate with C before
freezing it. The calibration score measures fit on the same dev data.

    python -m evaluation.calibrate --annotations path/to/dev.jsonl --inputs path/to/dev-policy-inputs.jsonl --grid path/to/grid.json --output evaluation/results/dev-threshold-candidate.json

The grid is a JSON object with a nonempty array of proposed values (each in
[0, 1]) for each of tau_ext, tau_ret, tau_e, and tau_c.

Provide one stage-input JSONL record per claim with claim_id, split (dev),
extraction_confidence, claim_low_quality, evidence_low_quality,
best_reranker_score (null if unavailable), numeric_slot_results (ordered
result strings), nli_results (label and the three class scores), and optional
part_outcomes (verdict strings). New engineering runs persist these inputs at the policy call site, including
ordered numeric slot indices, NLI scores, thresholds, and pre-reranking
candidate ranks, plus whether retrieval returned zero candidates. Apply migration 0007 and process a fresh dev PDF before
exporting the snapshot.

    python -m alembic upgrade head
    python -m evaluation.export_policy_inputs --dev-run-id <run-uuid> --output dev-policy-inputs.jsonl

Use this command only on runs from the development split. The export includes
the actual claim, document, and run UUIDs and the PDF SHA-256. Historical runs
without a capture are rejected. Use the separate native verdict export with
the checkpoint command to compare evidence anchors.

    python -m evaluation.synthetic_policy_probe

This probe uses actual B and C policy code with fixture stage signals. It
checks the nine draft perturbations and flags disagreements. It does not
run the retrieval or NLI models.

## Score the complete dev matrix

When C's runtime exports the effective configuration for each run, write a
manifest JSON object keyed by all eight experiment names. Give each key an
array of JSON report paths relative to the manifest. Score all runs against
the same dev annotation file in one command.

    python -m evaluation.score_matrix --annotations path/to/dev.jsonl --manifest path/to/manifest.json --output evaluation/results/dev-matrix

The command publishes the batch after all eight configurations match their
reports and score successfully. The upstream runtime still needs to execute
each configuration and record it in the report.

See [Open scientific claim verification pilot](datasets/open_corpus_pilot.md)
for dataset selection, attribution, physical PDF checks and the dev checkpoint.
