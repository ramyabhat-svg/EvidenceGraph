"""Measure agreement on two independently annotated train/dev files."""

import argparse
import json
from pathlib import Path

from evaluation.datasets.builder import read_jsonl, validate_splits
from evaluation.metrics.scoring import VERDICTS, cohen_kappa


def independently_labeled(path):
    """Index one person's labels by claim and require unique claim IDs."""
    if path.stem.casefold() == "test":
        raise ValueError("Use an independent train/dev annotation file.")
    labels = {}
    records = list(read_jsonl(path))
    validate_splits(records)
    for record in records:
        claim = record["claim_id"]
        if record["split"] == "test" or record["verdict"] not in VERDICTS:
            raise ValueError("Expected train/dev records with known verdicts.")
        if claim in labels:
            raise ValueError(f"Duplicate label for {claim}.")
        labels[claim] = record
    return labels


def main():
    """Write agreement counts and the claims that require adjudication."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    first, second = independently_labeled(args.first), independently_labeled(args.second)
    if not first or first.keys() != second.keys():
        parser.error("Both annotators must label the same nonempty claim subset.")
    disagreements = []
    pairs = []
    for claim in sorted(first):
        left, right = first[claim], second[claim]
        if (left["annotator_id"] == right["annotator_id"] or
                (left["paper_id"], left["split"]) != (right["paper_id"], right["split"])):
            parser.error(f"Expected two independent labels on the same source for {claim}.")
        pair = (left["verdict"], right["verdict"])
        pairs.append(pair)
        if pair[0] != pair[1]:
            disagreements.append({"claim_id": claim, "first": pair[0], "second": pair[1]})
    print(json.dumps({"count": len(pairs), "cohen_kappa": cohen_kappa(pairs),
                      "disagreements": disagreements}, indent=2))


if __name__ == "__main__":
    main()
