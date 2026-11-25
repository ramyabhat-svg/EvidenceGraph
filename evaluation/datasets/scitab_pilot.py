"""Select naturally sourced SciTab pilot claims and check available original PDFs."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

import pdfplumber

from eg_common.ids import derive_uuid
from worker.extraction.claims import extract_claims
from worker.ingestion.pdf_parser import ingest_pdf

NUMERIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent|points)", re.I)
TABLE = re.compile(r"^Table\s+(\d+)\b", re.I)
PREFERRED_PAPERS = ("1902.06423v1", "1906.01753v1", "1808.08672v2", "1801.07772v1")


def comparable(text):
    """Normalize typography and whitespace while preserving words and numbers."""
    return re.sub(r"\s+", "", text.casefold().replace("\u00ad", "").replace("\u2019", "'"))


def select(records, limit=12):
    """Select one supported quantitative statement per original paper."""
    by_paper = {}
    for row in records:
        text = row["claim"]
        table = TABLE.match(row["table_caption"])
        paper = row["paper_id"]
        root_id = re.sub(r"v\d+$", "", paper)
        if (
            row["label"] != "supports"
            or not NUMERIC.search(text)
            or not table
            or "[CONTINUE]" in text
            or root_id in by_paper
        ):
            continue
        by_paper[root_id] = {
            "paper_id": paper,
            "paper_title": row["paper"],
            "article_url": f"https://arxiv.org/abs/{paper}",
            "external_claim_id": row["id"],
            "external_table_id": row["table_id"],
            "claim_text": text,
            "external_verdict": row["label"],
            "published_table_number": int(table.group(1)),
            "split": "dev",
        }
    order = sorted(by_paper.values(), key=lambda item: (item["paper_id"] not in PREFERRED_PAPERS,))
    return order[:limit]


def inspect_pdf(row, path, live_document_id=None):
    """Report exact claim matches and candidate table pages from the unchanged PDF."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    document_id = live_document_id or UUID(int=0)
    chunks = ingest_pdf(path, document_id, digest)
    claims = extract_claims(chunks, digest)
    anchors = {chunk.anchor.anchor_id: chunk.anchor for chunk in chunks}
    text = comparable(row["claim_text"])
    matches = [claim for claim in claims if comparable(claim.claim_text) == text]
    number = row["published_table_number"]
    caption = re.compile(rf"^\s*Table\s+{number}\s*[:.]", re.I | re.M)
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    result = {
        "pdf_sha256": digest,
        "claim_text_pages": [idx for idx, page in enumerate(pages, 1) if text in comparable(page)],
        "table_caption_pages": [idx for idx, page in enumerate(pages, 1) if caption.search(page)],
        "exact_extractor_matches": [
            {
                "extractor_claim_id": str(claim.claim_id),
                "page": anchors[claim.source_anchor_id].page,
                "source_anchor_id": claim.source_anchor_id,
                "char_start": claim.char_start,
                "char_end": claim.char_end,
                "candidate_live_claim_id": str(
                    derive_uuid(
                        live_document_id,
                        claim.source_anchor_id,
                        claim.char_start,
                        claim.char_end,
                    )
                )
                if live_document_id
                else None,
            }
            for claim in matches
        ],
    }
    return result


def main():
    """Write an external pilot with optional original PDF checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.source.read_text(encoding="utf-8"))
    rows = select(data)
    for row in rows:
        path = args.pdf_dir / f'{row["paper_id"]}.pdf'
        if path.is_file() and path.stat().st_size:
            row["pdf_check"] = inspect_pdf(row, path)
    with args.output.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} pilot candidates from distinct papers.")


if __name__ == "__main__":
    main()
