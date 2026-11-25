"""Project, document, trace, review, and report endpoints."""

import hashlib
import html
import json
import secrets
from collections.abc import Iterator
from pathlib import Path, PureWindowsPath
from typing import Literal
from uuid import uuid4

import pdfplumber
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from eg_common.errors import AppError, ConflictError, NotFoundError
from eg_common.ids import derive_uuid
from eg_common.settings import Settings, get_settings
from persistence.session import get_session_factory
from persistence.workflow import (
    Claim,
    CompanionFile,
    Document,
    GraphEdge,
    Project,
    Review,
    Run,
    Trace,
)
from worker.orchestration.workflow import VERDICTS, enqueue, now


class ProjectInput(BaseModel):
    """Project creation request."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ReviewInput(BaseModel):
    """Append-only human review request."""
    model_config = ConfigDict(str_strip_whitespace=True)
    reviewer_id: str = Field(min_length=1, max_length=255)
    override_verdict: str
    note: str = Field(min_length=1)
    flag_for_rerun: bool = False


def save_upload(upload: UploadFile, root: Path, extension: str, limit: int) -> tuple[Path, str]:
    """Write a size-limited file to a server-generated path and hash its bytes."""
    field = f"{extension}_file"
    if Path(upload.filename or "").suffix.lower() != f".{extension}":
        raise AppError("invalid_file_type", f"Expected a .{extension} file.", field)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{secrets.token_hex(16)}.{extension}"
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.open("xb") as target:
            while block := upload.file.read(1024 * 1024):
                if size == 0 and extension == "pdf" and not block.startswith(b"%PDF-"):
                    raise AppError("invalid_file_type", "Invalid PDF signature.", field)
                size += len(block)
                if size > limit * 1024 * 1024:
                    raise AppError("file_too_large", f"File exceeds {limit} MB.", field, 413)
                if extension == "csv" and b"\x00" in block:
                    raise AppError("invalid_file_type", "CSV must contain text.", field)
                digest.update(block)
                target.write(block)
        if not size:
            raise AppError("invalid_file_type", "File is empty.", field)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination, digest.hexdigest()


def workflow_router(settings: Settings) -> APIRouter:
    """Attach the handoff routes to a configured app."""
    router = APIRouter(prefix="/api/v1")

    configured_factory = (
        None if settings.database_url == get_settings().database_url else
        sessionmaker(create_engine(settings.database_url, pool_pre_ping=True))
    )

    def session_dependency() -> Iterator[Session]:
        with (configured_factory or get_session_factory())() as session:
            yield session

    def project_output(session: Session, project: Project) -> dict:
        count = session.scalar(select(func.count()).select_from(Document)
                               .where(Document.project_id == project.id))
        return dict(project.data, document_count=count)

    def latest_trace(session: Session, claim_id: str) -> Trace:
        trace = session.scalar(select(Trace).join(Run).where(Trace.claim_id == claim_id)
                               .order_by(Run.queued_at.desc(), Run.id.desc()).limit(1))
        if trace is None:
            raise NotFoundError()
        return trace

    def history(session: Session, claim_id: str) -> list[dict]:
        reviews = session.scalars(select(Review).where(Review.claim_id == claim_id)
                                  .order_by(Review.created_at.desc(), Review.id.desc()))
        return [review.data for review in reviews]

    def run_output(run: Run) -> dict:
        return dict(run.data, status=run.status)

    @router.post("/projects", status_code=201)
    def create_project(body: ProjectInput, session: Session = Depends(session_dependency)) -> dict:
        """Create a named project."""
        project_id = str(uuid4())
        data = dict(body.model_dump(), project_id=project_id, created_at=now())
        session.add(Project(id=project_id, data=data))
        session.commit()
        return dict(data, document_count=0)

    @router.get("/projects")
    def list_projects(session: Session = Depends(session_dependency)) -> dict:
        """List projects and their document counts."""
        projects = [project_output(session, row) for row in session.scalars(select(Project))]
        projects.sort(key=lambda project: project["created_at"], reverse=True)
        return {"projects": projects, "total": len(projects)}

    @router.get("/projects/{project_id}")
    def get_project(project_id: str, session: Session = Depends(session_dependency)) -> dict:
        """Retrieve a project's details."""
        project = session.get(Project, project_id)
        if project is None:
            raise NotFoundError()
        return project_output(session, project)

    @router.post("/projects/{project_id}/documents", status_code=202)
    def upload_document(
        project_id: str,
        pdf_file: UploadFile = File(...),
        csv_file: UploadFile | None = File(None),
        document_name: str | None = Form(None),
        session: Session = Depends(session_dependency),
    ) -> dict:
        """Upload a PDF and at most one companion CSV and queue automatic analysis."""
        if session.get(Project, project_id) is None:
            raise NotFoundError()
        paths: list[Path] = []
        try:
            pdf, pdf_hash = save_upload(pdf_file, settings.storage_root, "pdf", settings.max_pdf_mb)
            paths.append(pdf)
            try:
                with pdfplumber.open(pdf) as reader:
                    page_count = len(reader.pages)
            except Exception as exc:
                raise AppError("invalid_file_type", "Could not read the PDF.", "pdf_file") from exc
            if page_count > settings.max_pdf_pages:
                raise AppError("file_too_large", "PDF exceeds the page limit.", "pdf_file", 413)
            csv_name = csv_hash = None
            if csv_file is not None:
                csv, csv_hash = save_upload(
                    csv_file, settings.storage_root, "csv", settings.max_csv_mb,
                )
                paths.append(csv)
                csv_name = csv.name
            document_id = str(uuid4())
            data = {
                "document_id": document_id, "project_id": project_id,
                "display_name": (document_name or "").strip() or
                PureWindowsPath(pdf_file.filename or "document.pdf").name,
                "pdf_sha256": pdf_hash, "csv_sha256": csv_hash, "created_at": now(),
                "page_count": page_count, "file_type": "pdf",
            }
            document = Document(id=document_id, project_id=project_id, pdf_hash=pdf_hash,
                                pdf_path=pdf.name, data=data)
            session.add(document)
            session.flush()
            if csv_name is not None and csv_hash is not None:
                session.add(CompanionFile(
                    document_id=document_id, storage_path=csv_name, file_hash=csv_hash,
                ))
            enqueue(session, document, str(uuid4()))
            session.commit()
        except IntegrityError as exc:
            for path in paths:
                path.unlink(missing_ok=True)
            session.rollback()
            duplicate = session.scalar(select(Document.id).where(
                Document.project_id == project_id, Document.pdf_hash == pdf_hash,
            ))
            if duplicate:
                raise ConflictError(
                    "duplicate_document", "PDF already exists.", "pdf_file"
                ) from exc
            raise
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        return document.data

    @router.get("/projects/{project_id}/documents")
    def list_documents(project_id: str, session: Session = Depends(session_dependency)) -> dict:
        """List the project's uploaded PDFs and status."""
        if session.get(Project, project_id) is None:
            raise NotFoundError()
        records = session.scalars(select(Document).where(Document.project_id == project_id))
        documents = sorted((row.data for row in records),
                           key=lambda document: document["created_at"], reverse=True)
        return {"project_id": project_id, "documents": documents, "total": len(documents)}

    @router.get("/documents/{document_id}")
    def get_document(document_id: str, session: Session = Depends(session_dependency)) -> dict:
        """Return upload metadata and current processing status."""
        document = session.get(Document, document_id)
        if document is None:
            raise NotFoundError()
        return document.data

    @router.post("/documents/{document_id}/analyze", status_code=202)
    def analyze(document_id: str, session: Session = Depends(session_dependency)) -> dict:
        """Queue a rerun or return the ID of the already queued analysis."""
        document = session.get(Document, document_id, with_for_update=True)
        if document is None:
            raise NotFoundError()
        run = session.scalar(select(Run).where(Run.document_id == document_id,
                                              Run.status == "queued").limit(1))
        if run is None:
            run = enqueue(session, document, str(uuid4()))
        session.commit()
        return {"document_id": document_id, "run_id": run.id, "status": run.status}

    @router.get("/documents/{document_id}/claims")
    def list_claims(
        document_id: str, status: str | None = None,
        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> dict:
        """Page through the latest completed run, optionally filtering verdicts."""
        if session.get(Document, document_id) is None:
            raise NotFoundError()
        if status is not None and status not in VERDICTS:
            raise AppError("invalid_status_filter", "Unknown claim verdict.", "status")
        run_id = session.scalar(select(Run.id).where(
            Run.document_id == document_id, Run.status == "complete",
        ).order_by(Run.queued_at.desc(), Run.id.desc()).limit(1))
        query = select(Trace).where(Trace.run_id == run_id)
        if status:
            query = query.where(Trace.data["verdict"]["verdict_status"].as_string() == status)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(Trace.claim_id)
                               .offset((page - 1) * page_size).limit(page_size))
        fields = ("claim_id", "claim_text", "claim_type", "source_anchor",
                  "extraction_method", "extraction_confidence")
        claims = [dict({key: row.data[key] for key in fields},
                       verdict_status=row.data["verdict"]["verdict_status"]) for row in rows]
        return {"document_id": document_id, "total": total, "page": page,
                "page_size": page_size, "claims": claims}

    @router.get("/claims/{claim_id}")
    def get_claim(claim_id: str, session: Session = Depends(session_dependency)) -> dict:
        """Retrieve the latest system trace and all human reviews."""
        return dict(latest_trace(session, claim_id).data, review_history=history(session, claim_id))

    @router.post("/claims/{claim_id}/reviews", status_code=201)
    def submit_review(
        claim_id: str, body: ReviewInput, session: Session = Depends(session_dependency),
    ) -> dict:
        """Append a review event and its provenance edge in one transaction."""
        if body.override_verdict not in VERDICTS:
            raise AppError("invalid_verdict", "Unknown override verdict.", "override_verdict")
        trace = latest_trace(session, claim_id)
        data = dict(body.model_dump(), review_id=str(uuid4()), claim_id=claim_id,
                    run_id=trace.run_id, created_at=now(),
                    previous_verdict=trace.data["verdict"]["verdict_status"])
        session.add(Review(id=data["review_id"], claim_id=claim_id, run_id=trace.run_id,
                           created_at=data["created_at"], data=data))
        session.flush()
        session.add(GraphEdge(from_id=claim_id, to_id=data["review_id"],
                              run_id=trace.run_id, edge_type="CLAIM_REVIEWED_BY"))
        session.commit()
        return data

    @router.get("/claims/{claim_id}/reviews")
    def get_reviews(claim_id: str, session: Session = Depends(session_dependency)) -> dict:
        """List all human reviews for a known claim."""
        if session.get(Claim, claim_id) is None:
            raise NotFoundError()
        reviews = history(session, claim_id)
        return {"claim_id": claim_id, "reviews": reviews, "total": len(reviews)}

    @router.get("/projects/{project_id}/runs")
    def list_runs(
        project_id: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> dict:
        """Page through project runs in reverse queue order."""
        if session.get(Project, project_id) is None:
            raise NotFoundError()
        query = select(Run).join(Document).where(Document.project_id == project_id)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(Run.queued_at.desc(), Run.id.desc())
                               .offset((page - 1) * page_size).limit(page_size))
        runs = [dict(run_output(row), **row.data["configuration"]) for row in rows]
        return {"project_id": project_id, "total": total, "page": page,
                "page_size": page_size, "runs": runs}

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, session: Session = Depends(session_dependency)) -> dict:
        """Return run status, configuration, and input hashes."""
        run = session.get(Run, run_id)
        if run is None:
            raise NotFoundError()
        return run_output(run)

    @router.get("/runs/{run_id}/report", response_model=None)
    def get_report(
        run_id: str, format: Literal["json", "html"] = "json",
        session: Session = Depends(session_dependency),
    ) -> dict | HTMLResponse:
        """Export a completed run and its trace data."""
        run = session.get(Run, run_id)
        if run is None:
            raise NotFoundError()
        if run.status != "complete":
            raise ConflictError("run_not_complete", "A report requires a completed run.")
        rows = session.scalars(select(Trace).where(Trace.run_id == run_id).order_by(Trace.claim_id))
        claims = [dict(row.data, review_history=[
            review for review in history(session, row.claim_id) if review["run_id"] == run_id
        ]) for row in rows]
        summary = {verdict: 0 for verdict in VERDICTS}
        for claim in claims:
            summary[claim["verdict"]["verdict_status"]] += 1
        report = {
            "report_id": str(derive_uuid(run_id, "report")), "run_id": run_id,
            "project_id": run.data["project_id"], "document_id": run.document_id,
            "generated_at": run.data["completed_at"],
            "pipeline_versions": run.data["configuration"],
            "input_hashes": run.data["input_hashes"],
            "summary": dict(summary, total_claims=len(claims)), "claims": claims,
            "limitations": "Text-based English PDFs only. Retrieval and policy are fallback stubs.",
        }
        if format == "html":
            body = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
            return HTMLResponse(f"<!doctype html><html lang='en'><meta charset='utf-8'>"
                                f"<title>EvidenceGraph report</title><h1>Analysis report</h1>"
                                f"<pre>{body}</pre></html>")
        return report

    return router


