"""Inspect extraction volume on explicitly selected train/dev papers."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from worker.extraction.claims import extract_claims
from worker.ingestion.pdf_parser import ingest_pdf


def main():
    """Write a parser probe without producing claim verdicts or accuracy scores."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path)
    args = parser.parse_args()
    if any("test" in {part.casefold() for part in path.parts} for path in args.pdfs):
        parser.error("Use explicitly selected train/dev PDFs.")
    results = []
    for pdf in args.pdfs:
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        chunks = ingest_pdf(pdf, uuid5(NAMESPACE_URL, digest), digest)
        claims = extract_claims(chunks, digest)
        results.append(
            {
                "paper_id": pdf.stem,
                "sha256": digest,
                "chunks": len(chunks),
                "anchor_types": dict(Counter(chunk.anchor.kind.value for chunk in chunks)),
                "claims": len(claims),
                "numeric_claims": sum(bool(claim.numeric_slots) for claim in claims),
            }
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
