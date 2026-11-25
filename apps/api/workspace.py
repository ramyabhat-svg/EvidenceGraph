"""Project and review views of the native engineering pipeline."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.documents import _file_type, _remove_stored_file, _store_upload
from domain.entities import VerdictStatus
from eg_common.errors import AppError, ConflictError, NotFoundError
from eg_common.settings import Settings
from persistence.models import (
    AnalysisRunRow,
    Base,
    ClaimRow,
    DocumentRow,
    EvidenceChunkRow,
    NLIResultRow,
    NumericCheckRow,
    ProjectRow,
    RerankerResultRow,
    SourceLocationRow,
    VerdictEvidenceRow,
    VerdictRow,
    VerificationResultRow,
    WorkspaceReviewRow,
)
from persistence.repositories import PersistenceRepository

Payload = dict[str, Any]
Row = TypeVar("Row", bound=Base)


class ProjectInput(BaseModel):
    """User-supplied project metadata."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ReviewInput(BaseModel):
    """A human decision and its rationale."""

    model_config = ConfigDict(str_strip_whitespace=True)
    reviewer_id: str = Field(min_length=1, max_length=255)
    override_verdict: VerdictStatus
    note: str = Field(min_length=1)
    flag_for_rerun: bool = False


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _get(db: Session, table: type[Row], key: UUID) -> Row:
    row = db.get(table, key)
    if row is None:
        raise NotFoundError()
    return row


def _project(db: Session, row: ProjectRow) -> Payload:
    count = db.scalar(
        select(func.count(DocumentRow.id)).where(
            DocumentRow.project_id == row.id, DocumentRow.file_type == "pdf"
        )
    )
    return dict(
        project_id=row.id,
        name=row.name or str(row.id),
        description=row.description,
        created_at=_utc(row.created_at),
        document_count=count,
    )


def _document(db: Session, row: DocumentRow) -> Payload:
    files = PersistenceRepository(db).get_document_files(row.id)
    statuses = {file.status for file in files}
    status = next(s for s in ("error", "processing", "queued", "complete") if s in statuses)
    count = db.scalar(select(func.count(ClaimRow.id)).where(ClaimRow.document_id == row.id))
    return dict(
        document_id=row.id,
        project_id=row.project_id,
        status=status,
        display_name=row.display_name or row.filename,
        created_at=_utc(row.uploaded_at),
        claim_count=count if status == "complete" else None,
        progress_message=status,
        error_message=next((f.processing_error for f in files if f.processing_error), None),
    )


def _anchor(anchor: SourceLocationRow) -> Payload:
    return dict(
        element_type=anchor.kind,
        anchor_id=anchor.anchor_id,
        page=anchor.page,
        row=anchor.row,
        col=anchor.col,
        char_start=anchor.char_start,
        char_end=anchor.char_end,
        table_id=str(anchor.table_index) if anchor.table_index is not None else None,
    )


def _summary(db: Session, claim: ClaimRow, verdict: VerdictRow) -> Payload:
    return dict(
        claim_id=claim.id,
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        extraction_method=claim.extraction_method,
        extraction_confidence=claim.extraction_confidence,
        source_anchor=_anchor(_get(db, SourceLocationRow, claim.source_location_id)),
        verdict_status=verdict.status,
    )


def _latest(db: Session, claim_id: UUID) -> VerdictRow:
    verdict = db.scalar(
        select(VerdictRow)
        .join(AnalysisRunRow)
        .where(VerdictRow.claim_id == claim_id)
        .order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id.desc())
        .limit(1)
    )
    if verdict is None:
        raise NotFoundError("The claim has no completed verdict.")
    return verdict


def _review(review: WorkspaceReviewRow, verdict: VerdictRow) -> Payload:
    return dict(
        review_id=review.id,
        claim_id=verdict.claim_id,
        run_id=verdict.run_id,
        reviewer_id=review.reviewer_id,
        override_verdict=review.override_verdict,
        previous_verdict=verdict.status,
        note=review.note,
        flag_for_rerun=review.flag_for_rerun,
        created_at=_utc(review.created_at),
    )


def _history(db: Session, claim_id: UUID, run_id: UUID | None = None) -> list[Payload]:
    query = (
        select(WorkspaceReviewRow, VerdictRow)
        .join(VerdictRow)
        .where(VerdictRow.claim_id == claim_id)
    )
    if run_id is not None:
        query = query.where(VerdictRow.run_id == run_id)
    return [
        _review(r, v)
        for r, v in db.execute(
            query.order_by(WorkspaceReviewRow.created_at.desc(), WorkspaceReviewRow.id.desc())
        )
    ]


def _trace(db: Session, claim: ClaimRow, verdict: VerdictRow, run: AnalysisRunRow) -> Payload:
    nli = db.scalars(
        select(NLIResultRow).where(NLIResultRow.claim_id == claim.id, NLIResultRow.run_id == run.id)
    ).all()
    scores: dict[UUID, float] = {
        evidence_id: score
        for evidence_id, score in db.execute(
            select(RerankerResultRow.evidence_chunk_id, RerankerResultRow.score).where(
                RerankerResultRow.claim_id == claim.id, RerankerResultRow.run_id == run.id
            )
        )
    }
    checks = db.execute(
        select(NumericCheckRow, VerificationResultRow.reason)
        .join(VerificationResultRow)
        .where(VerificationResultRow.claim_id == claim.id, VerificationResultRow.run_id == run.id)
        .order_by(VerificationResultRow.slot_index, NumericCheckRow.check_index)
    ).all()
    ids = set(
        db.scalars(
            select(VerdictEvidenceRow.evidence_chunk_id).where(
                VerdictEvidenceRow.verdict_id == verdict.id
            )
        )
    ).union(scores, (n.evidence_chunk_id for n in nli), (c.evidence_chunk_id for c, _ in checks))
    policy_inputs = verdict.policy_inputs or {}
    retrieval = {
        str(item["evidence_id"]): item
        for item in policy_inputs.get("retrieval", [])
        if isinstance(item, dict) and "evidence_id" in item
    }
    evidence = []
    for chunk, location in db.execute(
        select(EvidenceChunkRow, SourceLocationRow)
        .join(SourceLocationRow, SourceLocationRow.id == EvidenceChunkRow.source_location_id)
        .where(EvidenceChunkRow.id.in_(ids))
        .order_by(EvidenceChunkRow.id)
    ):
        evidence.append(
            dict(
                evidence_id=chunk.id,
                document_id=chunk.document_id,
                evidence_text=chunk.text,
                source_anchor=_anchor(location),
                retrieval_rank=(
                    retrieval.get(str(chunk.id), {}).get("retrieval_rank")
                ),
                relevance_rank=retrieval.get(str(chunk.id), {}).get("rank"),
                retrieval_score=retrieval.get(str(chunk.id), {}).get("retrieval_score"),
                bm25_score=retrieval.get(str(chunk.id), {}).get("bm25_score"),
                dense_score=retrieval.get(str(chunk.id), {}).get("dense_score"),
                bm25_rank=retrieval.get(str(chunk.id), {}).get("bm25_rank"),
                dense_rank=retrieval.get(str(chunk.id), {}).get("dense_rank"),
                rrf_score=retrieval.get(str(chunk.id), {}).get("rrf_score"),
                reranker_score=scores.get(chunk.id),
            )
        )
    evidence.sort(
        key=lambda item: (
            item["relevance_rank"] is None,
            item["relevance_rank"] if item["relevance_rank"] is not None else 0,
            str(item["evidence_id"]),
        )
    )
    return dict(
        _summary(db, claim, verdict),
        document_id=claim.document_id,
        numeric_slots=claim.numeric_slots,
        retrieved_evidence=evidence,
        nli_results=[
            dict(
                evidence_id=n.evidence_chunk_id,
                label=n.label,
                model_name=n.model_id,
                model_revision=n.model_revision,
                probabilities=dict(
                    contradiction=n.contradiction_score,
                    entailment=n.entailment_score,
                    neutral=n.neutral_score,
                ),
            )
            for n in nli
        ],
        numeric_checks=[
            dict(
                evidence_id=c.evidence_chunk_id,
                result=c.result,
                trace=c.trace,
                tolerance=format(c.tolerance, "f") if c.tolerance is not None else None,
                incomparable_reason=reason if c.result == "incomparable" else None,
            )
            for c, reason in checks
        ],
        verdict=dict(
            verdict_status=verdict.status,
            policy_rule_fired=None,
            policy_version=verdict.policy_version,
            abstention_reason=verdict.reason if verdict.status == "Needs Review" else None,
            reason=verdict.reason,
            explanation=verdict.explanation,
            confidence=verdict.confidence,
            policy_inputs=policy_inputs,
            run_id=run.id,
            run_timestamp=_utc(run.completed_at or run.created_at),
        ),
    )


def _run(db: Session, run: AnalysisRunRow) -> Payload:
    doc = _get(db, DocumentRow, run.document_id)
    companion = db.scalar(
        select(DocumentRow.file_hash).where(DocumentRow.parent_document_id == doc.id)
    )
    count = db.scalar(select(func.count(VerdictRow.id)).where(VerdictRow.run_id == run.id))
    return dict(
        run_id=run.id,
        document_id=doc.id,
        started_at=_utc(run.created_at),
        completed_at=_utc(run.completed_at),
        status="complete",
        claim_count=count,
        error_count=0,
        policy_version=run.policy_version,
        configuration=run.configuration,
        model_versions=run.model_versions,
        input_hashes=dict(pdf_sha256=doc.file_hash, csv_sha256=companion),
    )


def create_workspace_router(settings: Settings, sessions: sessionmaker[Session]) -> APIRouter:
    """Adapt persisted engineering records for the review workspace."""
    router = APIRouter(prefix="/workspace")

    @router.post("/projects", status_code=201)
    def create_project(body: ProjectInput) -> Payload:
        """Create a named engineering project."""
        with sessions.begin() as db:
            project = ProjectRow(**body.model_dump(), created_at=datetime.now(timezone.utc))
            db.add(project)
            db.flush()
            return _project(db, project)

    @router.get("/projects")
    def projects() -> Payload:
        """List projects in creation order."""
        with sessions() as db:
            rows = [
                _project(db, p)
                for p in db.scalars(
                    select(ProjectRow).order_by(
                        ProjectRow.created_at.desc().nulls_last(), ProjectRow.id
                    )
                )
            ]
            return dict(projects=rows, total=len(rows))

    @router.get("/projects/{project_id}")
    def project(project_id: UUID) -> Payload:
        """Read a single project."""
        with sessions() as db:
            return _project(db, _get(db, ProjectRow, project_id))

    @router.get("/projects/{project_id}/documents")
    def documents(project_id: UUID) -> Payload:
        """List papers and combined PDF/CSV worker status."""
        with sessions() as db:
            _get(db, ProjectRow, project_id)
            docs = [
                _document(db, d)
                for d in db.scalars(
                    select(DocumentRow)
                    .where(DocumentRow.project_id == project_id, DocumentRow.file_type == "pdf")
                    .order_by(DocumentRow.uploaded_at.desc().nulls_last(), DocumentRow.id)
                )
            ]
            return dict(project_id=project_id, documents=docs, total=len(docs))

    @router.post("/projects/{project_id}/documents", status_code=202)
    def upload(
        project_id: UUID,
        pdf_file: UploadFile = File(...),
        csv_file: UploadFile | None = File(None),
        document_name: str | None = Form(None, max_length=512),
    ) -> Payload:
        """Validate and queue the PDF and optional companion in one transaction."""
        paths: list[Path] = []
        pdf_id = uuid4()
        try:
            with sessions.begin() as db:
                _get(db, ProjectRow, project_id)
                repo = PersistenceRepository(db)
                for file, kind, uid, parent in [
                    (pdf_file, "pdf", pdf_id, None),
                    (csv_file, "csv", uuid4(), pdf_id),
                ]:
                    if file is None:
                        continue
                    filename = file.filename or ""
                    if len(filename) > 512 or _file_type(filename) != kind:
                        raise AppError(
                            "invalid_file_type",
                            "Choose a valid file for this field.",
                            kind + "_file",
                        )
                    path, digest = _store_upload(
                        file,
                        settings=settings,
                        project_id=project_id,
                        document_id=uid,
                        file_type=_file_type(filename),
                    )
                    paths.append(path)
                    repo.create_document(
                        document_id=uid,
                        project_id=project_id,
                        filename=Path(filename).name,
                        file_hash=digest,
                        storage_path=str(path),
                        file_type=kind,
                        parent_document_id=parent,
                    )
                doc = _get(db, DocumentRow, pdf_id)
                doc.display_name = (document_name or "").strip() or doc.filename
                doc.uploaded_at = datetime.now(timezone.utc)
                result = _document(db, doc)
            return result
        except Exception as exc:
            for path in paths:
                _remove_stored_file(path, project_id)
            if isinstance(exc, IntegrityError):
                raise ConflictError(
                    "document_conflict", "An upload conflicts with an existing document."
                ) from exc
            raise

    @router.get("/documents/{document_id}")
    def document(document_id: UUID) -> Payload:
        """Read a paper and its processing state."""
        with sessions() as db:
            return _document(db, _get(db, DocumentRow, document_id))

    @router.get("/documents/{document_id}/claims")
    def claims(
        document_id: UUID,
        status: VerdictStatus | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> Payload:
        """Page through claims from the latest run with optional verdict filtering."""
        with sessions() as db:
            _get(db, DocumentRow, document_id)
            last = (
                select(AnalysisRunRow.id)
                .where(AnalysisRunRow.document_id == document_id)
                .order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id.desc())
                .limit(1)
                .scalar_subquery()
            )
            query = select(ClaimRow, VerdictRow).join(VerdictRow).where(VerdictRow.run_id == last)
            if status:
                query = query.where(VerdictRow.status == status.value)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            rows = db.execute(
                query.order_by(ClaimRow.char_start, ClaimRow.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return dict(
                document_id=document_id,
                total=total,
                page=page,
                page_size=page_size,
                claims=[_summary(db, c, v) for c, v in rows],
            )

    @router.get("/claims/{claim_id}")
    def claim_detail(claim_id: UUID) -> Payload:
        """Return the native trace and human review history."""
        with sessions() as db:
            claim = _get(db, ClaimRow, claim_id)
            verdict = _latest(db, claim_id)
            return dict(
                _trace(db, claim, verdict, _get(db, AnalysisRunRow, verdict.run_id)),
                review_history=_history(db, claim_id),
            )

    @router.get("/claims/{claim_id}/reviews")
    def reviews(claim_id: UUID) -> Payload:
        """Read chronological review history for a claim."""
        with sessions() as db:
            _get(db, ClaimRow, claim_id)
            rows = _history(db, claim_id)
            return dict(claim_id=claim_id, reviews=rows, total=len(rows))

    @router.post("/claims/{claim_id}/reviews", status_code=201)
    def review(claim_id: UUID, body: ReviewInput) -> Payload:
        """Record a human decision against the current system verdict."""
        with sessions.begin() as db:
            verdict = _latest(db, claim_id)
            event = WorkspaceReviewRow(verdict_id=verdict.id, **body.model_dump(mode="json"))
            db.add(event)
            db.flush()
            return _review(event, verdict)

    @router.get("/projects/{project_id}/runs")
    def runs(
        project_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)
    ) -> Payload:
        """List stored analysis runs for project papers."""
        with sessions() as db:
            _get(db, ProjectRow, project_id)
            query = (
                select(AnalysisRunRow)
                .join(DocumentRow)
                .where(DocumentRow.project_id == project_id, DocumentRow.file_type == "pdf")
            )
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            results = db.scalars(
                query.order_by(AnalysisRunRow.created_at.desc(), AnalysisRunRow.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return dict(
                runs=[_run(db, r) for r in results], page=page, page_size=page_size, total=total
            )

    @router.get("/runs/{run_id}")
    def run_detail(run_id: UUID) -> Payload:
        """Read the engineering run configuration and file hashes."""
        with sessions() as db:
            return _run(db, _get(db, AnalysisRunRow, run_id))

    @router.get("/runs/{run_id}/report", response_model=None)
    def report(run_id: UUID, format: Literal["json", "html"] = "json") -> Payload | HTMLResponse:
        """Export the selected run and its run-specific review events."""
        with sessions() as db:
            run = _get(db, AnalysisRunRow, run_id)
            rows = db.execute(
                select(ClaimRow, VerdictRow)
                .join(VerdictRow)
                .where(VerdictRow.run_id == run_id)
                .order_by(ClaimRow.id)
            )
            traces = [
                dict(_trace(db, c, v, run), review_history=_history(db, c.id, run_id))
                for c, v in rows
            ]
            data = dict(_run(db, run), claims=traces, summary=dict(total_claims=len(traces)))
            if format == "json":
                return data
            body = html.escape(json.dumps(jsonable_encoder(data), ensure_ascii=False, indent=2))
            return HTMLResponse(
                "<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>Analysis report</title>"
                f"<h1>Analysis report</h1><pre>{body}</pre></html>"
            )

    return router
