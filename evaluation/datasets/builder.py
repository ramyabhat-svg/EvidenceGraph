"""Validate annotation splits and export dev retrieval queries."""

import argparse
import json
from pathlib import Path


def read_jsonl(path):
    """Read records and retain line context on invalid input."""
    with Path(path).open(encoding="utf-8-sig") as source:
        for index, line in enumerate(source, 1):
            if line.strip():
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("Expected a JSON object")
                    yield record
                except ValueError as exc:
                    raise ValueError(f"{path}, line {index}: {exc}") from exc


def validate_splits(records):
    """Detect document leakage and duplicate annotation IDs."""
    papers = {}
    seen = set()
    for record in records:
        annotation = record["annotation_id"]
        if annotation in seen:
            raise ValueError(f"Duplicate annotation ID: {annotation}")
        seen.add(annotation)
        split = record["split"]
        if split not in {"train", "dev", "test"}:
            raise ValueError(f"Unknown split: {split}")
        paper = record["paper_id"]
        if papers.setdefault(paper, split) != split:
            raise ValueError(f"Document crosses data splits: {paper}")


def export_retrieval(records):
    """Return dev queries with at least one human-identified evidence anchor."""
    for record in records:
        if record["split"] != "dev":
            continue
        anchors = record.get("expected_evidence_anchors") or (
            [record["evidence_anchor"]] if record.get("evidence_anchor") else []
        )
        if anchors:
            yield {"claim_id": record["claim_id"], "claim_text": record["claim_text"],
                   "expected_evidence_anchors": anchors}


def main():
    """Build a retrieval query file from human train/dev records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.annotations.stem.casefold() == "test":
        parser.error("Use train/dev annotations.")
    records = list(read_jsonl(args.annotations))
    if any(record.get("split") == "test" for record in records):
        parser.error("Use train/dev annotations.")
    validate_splits(records)
    with args.output.open("x", encoding="utf-8") as destination:
        for query in export_retrieval(records):
            destination.write(json.dumps(query, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
