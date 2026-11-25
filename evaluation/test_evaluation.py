"""Tests for D's deterministic development tooling."""

from collections import Counter

import pytest

from evaluation.baselines.runner import evaluate
from evaluation.datasets.builder import export_retrieval, validate_splits
from evaluation.datasets.synthetic import RULES, generate
from evaluation.metrics.scoring import calibration, cohen_kappa, risk_coverage


def test_draft_is_reproducible_and_balanced():
    cases = list(generate(42, 10))
    assert cases == list(generate(42, 10))
    assert cases != list(generate(43, 10))
    assert Counter(case["perturbation_type"] for case in cases) == dict.fromkeys(RULES, 10)
    assert len({case["synthetic_id"] for case in cases}) == 90
    removed = [case for case in cases if case["perturbation_type"] == "evidence_removed"]
    assert all(
        case["evidence_text"] is None and case["evidence_anchor"] is None for case in removed
    )


def test_split_guard_and_dev_retrieval_export():
    anchor = {"element_type": "csv_row", "row": 1}
    row = {
        "annotation_id": "a",
        "paper_id": "one",
        "split": "dev",
        "claim_id": "c",
        "claim_text": "A claim",
        "evidence_anchor": anchor,
    }
    assert list(export_retrieval([row]))[0]["expected_evidence_anchors"] == [anchor]
    with pytest.raises(ValueError, match="crosses"):
        validate_splits([row, dict(row, annotation_id="b", split="test")])


def test_scorer_uses_ranked_evidence_and_counts_missing_claims():
    anchor = {"element_type": "csv_row", "row": 1}
    gold = {
        "paper_id": "one",
        "claim_id": "one",
        "verdict": "Supported",
        "evidence_anchor": anchor,
        "expected_numeric_result": "match",
    }
    trace = {
        "claim_id": "one",
        "verdict": {"verdict_status": "Supported"},
        "retrieved_evidence": [{"evidence_id": "a", "retrieval_rank": 2, "source_anchor": anchor}],
        "nli_results": [{"evidence_id": "a", "probabilities": {"entailment": 0.8}}],
        "numeric_checks": [{"evidence_id": "a", "result": "match"}],
    }
    result = evaluate([gold, dict(gold, claim_id="two")], [trace])
    assert result["classification"]["macro_f1"] == 1
    assert result["extraction_recall"] == 0.5
    assert result["missing_claim_ids"] == ["two"]
    assert result["retrieval"] == {"recall_at_1": 0, "recall_at_5": 1, "recall_at_10": 1}
    assert result["numeric_mismatch"]["count"] == 1
    assert result["nli_entailment_calibration"]["brier"] == pytest.approx(0.04)


def test_agreement_calibration_and_risk_coverage():
    assert cohen_kappa([("A", "A"), ("B", "B")]) == 1
    assert cohen_kappa([("A", "B"), ("B", "A")]) == -1
    assert calibration([(1.0, True), (0.0, False)])["ece"] == 0
    curve = risk_coverage([(0.8, True), (0.8, False), (0.6, True)])
    assert curve[0] == {"threshold": 0.8, "coverage": 2 / 3, "risk": 0.5}


def test_draft_numeric_cases_with_member_b():
    from worker.extraction.slots import parse_all_numeric_slots
    from worker.verification.numeric import compare_slots

    expected = {
        "value_beyond_tolerance": "mismatch",
        "value_within_tolerance": "match",
        "unit_scale_swap": "mismatch",
        "unit_incomparable": "incomparable",
        "period_condition_swap": "incomparable",
        "percent_vs_pp_swap": "incomparable",
        "entity_swap": "incomparable",
        "low_quality_anchor": "match",
    }
    for case in generate(42, 10):
        (claim,) = parse_all_numeric_slots(case["perturbed_claim_text"])
        if case["evidence_text"] is not None:
            (evidence,) = parse_all_numeric_slots(case["evidence_text"])
            assert (
                compare_slots(claim, evidence).result.value == expected[case["perturbation_type"]]
            )


def test_engineering_dev_snapshot(tmp_path, monkeypatch):
    import json
    import sys
    from uuid import UUID

    from evaluation.run_eval import main

    claim_id = str(UUID(int=1))
    payload = {
        "analysis_run_id": str(UUID(int=2)),
        "document_id": str(UUID(int=3)),
        "verdicts": [
            {
                "claim_id": claim_id,
                "status": "Needs Review",
                "confidence": None,
                "reason": "threshold_unavailable:tau_ext",
                "policy_version": "decision-policy-v1",
                "explanation": [],
                "evidence": [
                    {
                        "evidence_chunk_id": "first",
                        "kind": "table_row",
                        "page": 1,
                        "table_index": 0,
                        "row": 1,
                        "col": None,
                        "char_start": None,
                        "char_end": None,
                    },
                    {
                        "evidence_chunk_id": "second",
                        "kind": "table_row",
                        "page": 2,
                        "table_index": 0,
                        "row": 1,
                        "col": None,
                        "char_start": None,
                        "char_end": None,
                    },
                ],
                "reranker_results": [
                    {"evidence_chunk_id": "first", "score": 0.2},
                    {"evidence_chunk_id": "second", "score": 0.9},
                ],
                "numeric_verifications": [],
                "nli_results": [
                    {
                        "evidence_chunk_id": "second",
                        "entailment_score": 0.7,
                        "contradiction_score": 0.2,
                        "neutral_score": 0.1,
                    }
                ],
            }
        ],
    }
    gold = {
        "annotation_id": "fixture",
        "paper_id": "one",
        "split": "dev",
        "claim_id": claim_id,
        "verdict": "Supported",
        "evidence_anchor": {
            "element_type": "table_row",
            "page": 2,
            "table_id": "table-0",
            "row": 1,
        },
    }
    report = tmp_path / "native.json"
    annotations = tmp_path / "dev.jsonl"
    output = tmp_path / "diagnostics.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    annotations.write_text(json.dumps(gold), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_eval",
            "--experiment",
            "full_system",
            "--split",
            "dev",
            "--annotations",
            str(annotations),
            "--report",
            str(report),
            "--output",
            str(output),
            "--engineering-verdicts",
        ],
    )
    main()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["configuration"] is None
    assert result["mode"] == "unattested_engineering_dev_diagnostics"
    assert result["metrics"]["reranked_evidence"]["recall_at_1"] == 1
    assert result["metrics"]["nli_entailment_calibration"]["brier"] == pytest.approx(0.09)
    assert result["metrics"]["abstention_rate"] == 1


def test_calibration_replays_archived_policy_and_selects_dev_grid():
    from evaluation.calibrate import fit

    def row(claim, confidence):
        return {
            "claim_id": claim,
            "extraction_confidence": confidence,
            "claim_low_quality": False,
            "evidence_low_quality": False,
            "best_reranker_score": 0.9,
            "numeric_slot_results": [],
            "nli_results": [
                {
                    "label": "entailment",
                    "entailment_score": 0.95,
                    "contradiction_score": 0.02,
                    "neutral_score": 0.03,
                }
            ],
        }

    gold = [
        {
            "annotation_id": "a",
            "claim_id": "a",
            "paper_id": "doc",
            "split": "dev",
            "verdict": "Supported",
        },
        {
            "annotation_id": "b",
            "claim_id": "b",
            "paper_id": "doc",
            "split": "dev",
            "verdict": "Needs Review",
        },
    ]
    candidates = {"tau_ext": [0.1, 0.7], "tau_ret": [0.5], "tau_e": [0.8], "tau_c": [0.8]}
    scores = fit(gold, [row("a", 0.9), row("b", 0.3)], candidates)
    assert scores["thresholds"]["tau_ext"] == 0.7
    assert scores["classification"]["macro_f1"] == 1
    assert scores["coverage"] == 0.5
    with pytest.raises(ValueError, match="dev-only"):
        fit([dict(gold[0], split="test")], [row("a", 0.9)], candidates)


def test_policy_replay_distinguishes_empty_retrieval():
    from evaluation.synthetic_policy_probe import replay

    counts = replay()
    assert counts["evidence_removed"] == {"Unsupported": 10}
    assert counts["value_beyond_tolerance"] == {"Contradicted": 10}
    statuses = [(status, count) for group in counts.values() for status, count in group.items()]
    assert all(not status.startswith("difference:") for status, _ in statuses)
    assert sum(count for _, count in statuses) == 90


def test_matrix_requires_attested_configs_before_publishing(tmp_path):
    import json

    from evaluation.run_eval import EXPERIMENTS, ROOT
    from evaluation.score_matrix import main

    annotations = tmp_path / "dev.jsonl"
    annotations.write_text(
        json.dumps(
            {
                "annotation_id": "fixture",
                "claim_id": "claim",
                "paper_id": "paper",
                "verdict": "Supported",
                "split": "dev",
            }
        ),
        encoding="utf-8",
    )
    manifest = {}
    for experiment in EXPERIMENTS:
        config = json.loads((ROOT / "baselines/configs" / f"{experiment}.json").read_text())
        path = tmp_path / f"{experiment}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": experiment,
                    "pipeline_versions": {"policy": "v1"},
                    "experiment_config": config,
                    "claims": [
                        {
                            "claim_id": "claim",
                            "verdict": {"verdict_status": "Supported"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest[experiment] = [path.name]

    index = tmp_path / "manifest.json"
    index.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "results"
    argv = ["--annotations", str(annotations), "--manifest", str(index), "--output", str(output)]
    last_report = tmp_path / manifest[EXPERIMENTS[-1]][0]
    correct = last_report.read_text(encoding="utf-8")
    last_report.write_text(correct.replace('"experiment_config":', '"other":'), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(argv)
    assert not output.exists()
    last_report.write_text(correct, encoding="utf-8")
    main(argv)
    assert {path.stem for path in output.glob("*.json")} == set(EXPERIMENTS)


def test_checkpoint_distinguishes_uuid_stage_and_anchor_matches():
    from uuid import UUID

    from evaluation.dev_checkpoint import checkpoint

    claim, missing, document, run = [str(UUID(int=i)) for i in range(1, 5)]
    anchor = {"element_type": "table_cell", "page": 2, "table_id": "table-0", "row": 4, "col": 1}
    first = {
        "annotation_id": "a",
        "paper_id": "paper",
        "split": "dev",
        "claim_id": claim,
        "document_id": document,
        "verdict": "Supported",
        "adjudicated": True,
        "evidence_anchor": anchor,
    }
    second = dict(first, annotation_id="b", claim_id=missing)
    evidence = {"kind": "table_cell", "table_index": 0, "page": 2, "row": 4, "col": 1}
    report = {
        "analysis_run_id": run,
        "document_id": document,
        "verdicts": [{"claim_id": claim, "evidence": [evidence]}],
    }
    stages = [
        {
            "claim_id": claim,
            "analysis_run_id": run,
            "split": "dev",
            "extraction_confidence": 0.9,
            "claim_low_quality": False,
            "evidence_low_quality": False,
            "best_reranker_score": 0.8,
            "numeric_slot_results": ["match"],
            "nli_results": [],
        }
    ]
    hits = checkpoint([first, second], report, stages)["claims"]
    assert hits[0]["matched_anchor_count"] == 1
    assert hits[0]["policy_inputs_found"] and hits[0]["verdict_found"]
    assert not hits[1]["policy_inputs_found"] and not hits[1]["verdict_found"]
    with pytest.raises(ValueError, match="same|this dev run"):
        checkpoint([first], report, [dict(stages[0], analysis_run_id=document)])
