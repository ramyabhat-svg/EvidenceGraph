"""Score a saved API report against human annotations."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.baselines.engineering import normalize_run
from evaluation.baselines.runner import evaluate
from evaluation.datasets.builder import read_jsonl, validate_splits

ROOT = Path(__file__).resolve().parent
EXPERIMENTS = (
    "baseline_bm25_nli",
    "baseline_hybrid_nli",
    "baseline_hybrid_rerank_nli",
    "full_system",
    "ablation_no_dense",
    "ablation_no_reranker",
    "ablation_no_table_context",
    "ablation_no_abstention",
)


def main(argv=None):
    """Score explicit report exports and write source hashes with the metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=EXPERIMENTS, required=True)
    parser.add_argument("--split", choices=("train", "dev", "test"), required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fallback", action="store_true")
    parser.add_argument(
        "--engineering-verdicts",
        action="store_true",
        help="Score native API snapshots as dev diagnostics.",
    )
    parser.add_argument("--confirm-final-test", action="store_true")
    args = parser.parse_args(argv)
    if args.split == "test" and (
        not args.confirm_final_test or args.allow_fallback or args.experiment != "full_system"
    ):
        parser.error("Final test requires the full system and explicit authorization.")
    if args.engineering_verdicts and (
        args.split != "dev" or args.experiment != "full_system" or args.allow_fallback
    ):
        parser.error("Native verdict snapshots are supported only for full-system dev diagnostics.")
    if args.split != "test" and args.annotations.stem.casefold() == "test":
        parser.error("Select a train/dev annotation file.")
    if args.output.exists():
        parser.error("Output already exists. Choose a new path.")

    config_path = args.config or ROOT / "baselines/configs" / f"{args.experiment}.json"
    inputs = {}

    def read(path):
        data = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    config = read(config_path)
    if config["experiment_name"] != args.experiment:
        parser.error("Experiment and config disagree.")
    traces = []
    sources = []
    for path in args.report:
        report = read(path)
        if args.engineering_verdicts:
            run_id, native_traces = normalize_run(report)
            if any(source["run_id"] == run_id for source in sources):
                parser.error("A native run was supplied more than once.")
            traces.extend(native_traces)
            sources.append(
                {
                    "run_id": run_id,
                    "fallback": False,
                    "policy_versions": sorted(
                        {trace["verdict"]["policy_version"] for trace in native_traces}
                    ),
                }
            )
            continue
        versions = report["pipeline_versions"]
        fallback = any(str(value).startswith("stub-") for value in versions.values())
        if fallback and not args.allow_fallback:
            parser.error("Fallback report requires --allow-fallback for a smoke test.")
        if not fallback and report.get("experiment_config") != config:
            parser.error("The report must record the exact requested experiment config.")
        traces.extend(report["claims"])
        sources.append(
            {
                "run_id": report["run_id"],
                "pipeline_versions": versions,
                "input_hashes": report.get("input_hashes"),
                "fallback": fallback,
            }
        )

    records = list(read_jsonl(args.annotations))
    if args.split != "test" and any(record.get("split") == "test" for record in records):
        parser.error("Use a train/dev-only annotation file.")
    validate_splits(records)
    inputs[str(args.annotations)] = hashlib.sha256(args.annotations.read_bytes()).hexdigest()
    gold = [record for record in records if record["split"] == args.split]
    if not gold:
        parser.error("No human annotations in this split.")
    result = {
        "experiment": args.experiment,
        "split": args.split,
        "configuration": None if args.engineering_verdicts else config,
        "smoke_test": any(source["fallback"] for source in sources),
        "sources": sources,
        "sha256": inputs,
        "metrics": evaluate(gold, traces),
    }
    if args.engineering_verdicts:
        result["mode"] = "unattested_engineering_dev_diagnostics"
        result["metrics"]["reranked_evidence"] = result["metrics"].pop("retrieval")
        result["metrics"]["reranked_evidence_claim_count"] = result["metrics"].pop(
            "retrieval_claim_count"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
