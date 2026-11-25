"""Run Member B's real extraction and numeric verification with labelled C fallbacks."""

from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from domain.schemas import SourceAnchor
from eg_common.ids import derive_uuid
from eg_common.settings import Settings
from persistence.workflow import Claim, CompanionFile, Document, Run, Trace
from worker.extraction.claims import extract_claims
from worker.ingestion.csv_parser import ingest_csv
from worker.ingestion.pdf_parser import ScannedPdfError, ingest_pdf
from worker.verification.numeric import verify_numeric_claim

CONFIGURATION = {
    "policy_version": "stub-policy-v0",
    "retrieval_version": "stub-retrieval-v0",
    "nli_model": None,
    "embedding_model": None,
    "reranker_model": None,
}
VERDICTS = ("Supported", "Partially Supported", "Contradicted", "Unsupported", "Needs Review")


def now() -> str:
    """Return a sortable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def enqueue(session: Session, document: Document, run_id: str) -> Run:
    """Queue one run and publish the document's queued state atomically."""
    timestamp = now()
    run = Run(id=run_id, document_id=document.id, status="queued", queued_at=timestamp, data={
        "run_id": run_id, "document_id": document.id, "project_id": document.project_id,
        "started_at": None, "completed_at": None, "claim_count": None, "error_count": 0,
        "configuration": CONFIGURATION,
        "input_hashes": {key: document.data[key] for key in ("pdf_sha256", "csv_sha256")},
    })
    session.add(run)
    document.data = dict(
        document.data, status="queued", progress_stage="queued", progress_percent=0,
        progress_message="Waiting for analysis.", updated_at=timestamp, error_message=None,
        claim_count=None,
    )
    return run


def anchor_json(anchor: SourceAnchor) -> dict:
    """Translate Member B anchors into the frontend contract."""
    return {
        "page": anchor.page, "element_type": anchor.kind.value,
        "char_start": anchor.char_start, "char_end": anchor.char_end,
        "table_id": None if anchor.table_index is None else f"table-{anchor.table_index}",
        "row": anchor.row, "col": anchor.col, "bounding_box": anchor.bbox,
    }


def build_traces(
    document: Document, companion: CompanionFile | None, run: Run, root: Path,
) -> tuple[int, list[dict]]:
    """Extract anchored claims and expose numeric checks without asserting policy verdicts."""
    from uuid import UUID

    pdf = root / document.pdf_path
    with pdfplumber.open(pdf) as reader:
        page_count = len(reader.pages)
    chunks = ingest_pdf(pdf, UUID(document.id), document.pdf_hash)
    claims = extract_claims(chunks, document.pdf_hash)
    anchors = {chunk.anchor.anchor_id: chunk.anchor for chunk in chunks}
    if companion is not None:
        csv_hash = companion.file_hash
        csv_id = derive_uuid(document.id, "csv")
        chunks.extend(ingest_csv(root / companion.storage_path, csv_id, csv_hash))
    traces = []
    for claim in claims:
        claim_id = str(derive_uuid(
            document.id, claim.source_anchor_id, claim.char_start, claim.char_end,
        ))
        # The fallback supplies a bounded, deterministic candidate list for trace inspection.
        candidates = [chunk for chunk in chunks if chunk.anchor.anchor_id != claim.source_anchor_id]
        candidates = sorted(candidates, key=lambda chunk: (
            chunk.anchor.kind.value == "paragraph", chunk.anchor.anchor_id,
        ))[:5]
        evidence = [{
            "evidence_id": str(derive_uuid(document.id, chunk.chunk_id)),
            "evidence_text": chunk.text, "source_anchor": anchor_json(chunk.anchor),
            "retrieval_rank": rank, "bm25_score": None, "dense_score": None,
            "reranker_score": None,
        } for rank, chunk in enumerate(candidates, 1)]
        checks = [
            dict(
                check.model_dump(mode="json"),
                evidence_id=str(derive_uuid(document.id, chunk_id)),
                incomparable_reason=verification.reason if check.result == "incomparable" else None,
            )
            for verification in verify_numeric_claim(claim, candidates)
            for chunk_id, check in verification.per_evidence
        ]
        ranks = {item["evidence_id"]: item["retrieval_rank"] for item in evidence}
        checks.sort(key=lambda check: ranks[check["evidence_id"]])
        traces.append({
            "claim_id": claim_id, "document_id": document.id, "project_id": document.project_id,
            "claim_text": claim.claim_text, "claim_type": claim.claim_type.value,
            "extraction_method": claim.extraction_method,
            "extraction_confidence": claim.extraction_confidence,
            "source_anchor": anchor_json(anchors[claim.source_anchor_id]),
            "numeric_slots": [slot.model_dump(mode="json") for slot in claim.numeric_slots] or None,
            "retrieved_evidence": evidence, "nli_results": [], "numeric_checks": checks,
            "verdict": {"verdict_status": "Needs Review", "policy_rule_fired": None,
                        "abstention_reason": "policy_unavailable",
                        "policy_version": CONFIGURATION["policy_version"],
                        "run_id": run.id, "run_timestamp": now()},
        })
    return page_count, traces


def process_next(factory: sessionmaker[Session], settings: Settings) -> bool:
    """Process one queued job under a database lock and publish results together."""
    with factory.begin() as session:
        run = session.scalar(
            select(Run).where(Run.status == "queued").order_by(Run.queued_at, Run.id)
            .limit(1).with_for_update(skip_locked=True)
        )
        if run is None:
            return False
        document = session.get_one(Document, run.document_id)
        started = now()
        # A separate transaction publishes progress while the queue row stays locked.
        with factory.begin() as progress_session:
            progress_document = progress_session.get_one(Document, document.id)
            progress_document.data = dict(
                progress_document.data, status="processing", progress_stage="ingestion",
                progress_message="Analyzing document.", progress_percent=5, updated_at=started,
            )
        error = None
        try:
            page_count, traces = build_traces(
                document, session.get(CompanionFile, document.id), run, settings.storage_root,
            )
        except ScannedPdfError:
            error = "scanned_pdf_unsupported"
        except Exception:
            error = "parse_failed"
        completed = now()
        if error:
            run.status = "error"
            run.data = dict(run.data, started_at=started, completed_at=completed, error_count=1)
            document.data = dict(
                document.data, status="error", progress_stage="ingestion",
                progress_message="Document analysis failed.", error_message=error,
                updated_at=completed,
            )
            return True
        for trace in traces:
            claim_id = trace["claim_id"]
            if session.get(Claim, claim_id) is None:
                session.add(Claim(id=claim_id, document_id=document.id))
                session.flush()
            session.add(Trace(claim_id=claim_id, run_id=run.id, data=trace))
        run.status = "complete"
        run.data = dict(
            run.data, started_at=started, completed_at=completed, claim_count=len(traces)
        )
        document.data = dict(
            document.data, status="complete", progress_stage="done", progress_percent=100,
            progress_message="Analysis complete.", updated_at=completed, page_count=page_count,
            claim_count=len(traces),
        )
        return True


