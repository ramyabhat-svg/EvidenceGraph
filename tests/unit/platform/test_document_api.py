"""Route-level tests for intake, processing status, and verdict retrieval."""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.documents import create_document_router
from apps.api.main import create_app
from apps.api.schemas.documents import AnalysisRunVerdictsResponse, DocumentStatusResponse
from domain.entities import (
    NLIClassification,
    NLILabel,
    PersistedNLIResult,
    Verdict,
    VerdictStatus,
)
from domain.schemas import (
    AnchorKind,
    CheckResult,
    Claim,
    ClaimType,
    EvidenceChunk,
    IngestionResult,
    NumericCheck,
    NumericSlots,
    SourceAnchor,
)
from eg_common.errors import AppError
from eg_common.ids import derive_uuid
from eg_common.settings import Settings
from persistence.models import Base, DocumentRow
from persistence.repositories import PersistenceRepository
from worker.orchestration.decision_policy import POLICY_VERSION
from worker.orchestration.run_identity import analysis_run_id
from worker.verification.numeric import SlotVerification

RouteHandler = Callable[..., Any]


@pytest.fixture
def api_context(
    tmp_path: Path,
) -> Generator[tuple[APIRouter, sessionmaker[Session], Settings, UUID], None, None]:
    """Create an isolated API router, database, durable storage root, and project."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(_env_file=None, storage_root=tmp_path / "durable-storage")
    project_id = uuid4()
    with factory() as session, session.begin():
        PersistenceRepository(session).create_project(project_id)
    router = create_document_router(settings, factory)
    try:
        yield router, factory, settings, project_id
    finally:
        engine.dispose()


def _handler(router: APIRouter, name: str) -> RouteHandler:
    """Return a route handler by its declared operation name."""
    for route in router.routes:
        if getattr(route, "name", None) == name:
            return route.endpoint
    raise AssertionError(f"route {name} is not registered")


def _upload(filename: str, payload: bytes) -> UploadFile:
    """Build an in-memory multipart upload object for the route handler."""
    return UploadFile(filename=filename, file=BytesIO(payload))


def _source_chunk(document_id: UUID) -> EvidenceChunk:
    """Build a deterministic evidence chunk for persisted verdict fixtures."""
    text = "The model achieved 95% accuracy."
    anchor = SourceAnchor(
        anchor_id="paper:p1:para0",
        document_id=document_id,
        kind=AnchorKind.PARAGRAPH,
        page=1,
        char_start=0,
        char_end=len(text),
        extraction_method="api-test",
        parser_version="api-test-v1",
    )
    return EvidenceChunk(
        chunk_id=UUID(int=document_id.int + 1),
        document_id=document_id,
        anchor=anchor,
        text=text,
    )


def test_pdf_upload_is_durable_and_enqueued(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """PDF intake stores bytes under shared storage and creates a queued row."""
    router, factory, settings, project_id = api_context
    content = b"%PDF-1.7\napi test file"
    endpoint = _handler(router, "upload_document")
    response = endpoint(project_id, _upload("report.pdf", content), None)

    assert response.status == "queued"
    assert response.project_id == project_id
    assert response.file_type == "pdf"
    assert response.document_id == response.file_document_id
    route = next(route for route in router.routes if route.name == "upload_document")
    assert route.status_code == 202
    stored_file = settings.storage_root / str(project_id) / f"{response.file_document_id}.pdf"
    assert stored_file.read_bytes() == content
    with factory() as session:
        document = session.get(DocumentRow, response.file_document_id)
        assert document is not None
        assert document.storage_path == str(stored_file)
        assert document.status == "queued"


def test_csv_upload_requires_and_persists_same_project_pdf_parent(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """CSV intake uses the existing parent-PDF relationship and returns queued status."""
    router, factory, settings, project_id = api_context
    parent_id = uuid4()
    with factory() as session, session.begin():
        PersistenceRepository(session).create_document(
            document_id=parent_id,
            project_id=project_id,
            filename="report.pdf",
            file_hash="a" * 64,
            storage_path=str(settings.storage_root / str(project_id) / "parent.pdf"),
            file_type="pdf",
        )

    endpoint = _handler(router, "upload_document")
    response = endpoint(
        project_id,
        _upload("data.csv", b"metric,value\naccuracy,0.95\n"),
        parent_id,
    )

    assert response.file_type == "csv"
    assert response.document_id == parent_id
    assert response.file_document_id != parent_id
    assert response.parent_document_id == parent_id
    assert (settings.storage_root / str(project_id) / f"{response.file_document_id}.csv").is_file()
    with pytest.raises(AppError) as duplicate:
        endpoint(
            project_id,
            _upload("second.csv", b"metric,value\naccuracy,0.96\n"),
            parent_id,
        )
    assert duplicate.value.code == "companion_csv_exists"
    status = _handler(router, "get_document_status")(response.file_document_id)
    assert status.document_id == parent_id
    assert {item.file_document_id for item in status.files} == {
        parent_id,
        response.file_document_id,
    }


def test_invalid_uploads_use_structured_errors_and_clean_temporary_files(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """Unsupported, malformed, oversized, and unparented CSV uploads are rejected."""
    router, _factory, settings, project_id = api_context
    endpoint = _handler(router, "upload_document")
    cases = [
        (_upload("report.txt", b"text"), None, "invalid_file_type", 400),
        (_upload("report.pdf", b"not a pdf"), None, "invalid_file_content", 400),
        (_upload("data.csv", b"metric,value\na,1\n"), None, "parent_document_required", 400),
        (_upload("data.csv", b"\xff"), uuid4(), "invalid_file_content", 400),
    ]
    for upload, parent_id, code, status in cases:
        with pytest.raises(AppError) as error:
            endpoint(project_id, upload, parent_id)
        assert error.value.code == code
        assert error.value.http_status == status

    size_limited = create_document_router(
        Settings(_env_file=None, storage_root=settings.storage_root, max_pdf_mb=0),
        _factory,
    )
    with pytest.raises(AppError) as oversized:
        _handler(size_limited, "upload_document")(
            project_id,
            _upload("large.pdf", b"%PDF-1.7"),
            None,
        )
    assert oversized.value.code == "file_too_large"
    assert oversized.value.http_status == 413
    project_dir = settings.storage_root / str(project_id)
    assert list(project_dir.glob("*.uploading")) == []

    storage_file = project_dir / "not-a-directory"
    storage_file.write_text("block storage root", encoding="utf-8")
    unavailable = create_document_router(
        Settings(_env_file=None, storage_root=storage_file),
        _factory,
    )
    with pytest.raises(AppError) as storage_error:
        _handler(unavailable, "upload_document")(
            project_id,
            _upload("unavailable.pdf", b"%PDF-1.7"),
            None,
        )
    assert storage_error.value.code == "storage_unavailable"
    assert storage_error.value.http_status == 503


def test_missing_project_and_duplicate_pdf_are_reported(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """Unknown projects return 404 and repeated project PDFs return a stable 409 code."""
    router, _factory, _settings, project_id = api_context
    endpoint = _handler(router, "upload_document")
    with pytest.raises(AppError) as missing:
        endpoint(uuid4(), _upload("report.pdf", b"%PDF-1.7\nunique"), None)
    assert missing.value.code == "not_found"
    assert missing.value.http_status == 404

    payload = b"%PDF-1.7\nrepeat"
    endpoint(project_id, _upload("first.pdf", payload), None)
    with pytest.raises(AppError) as duplicate:
        endpoint(project_id, _upload("second.pdf", payload), None)
    assert duplicate.value.code == "duplicate_document"
    assert duplicate.value.http_status == 409


def test_status_returns_queued_state_and_missing_document_error(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """Status lookup reflects queue state and exposes persisted run IDs."""
    router, _factory, _settings, project_id = api_context
    created = _handler(router, "upload_document")(
        project_id,
        _upload("report.pdf", b"%PDF-1.7\nstatus"),
        None,
    )
    status = _handler(router, "get_document_status")(created.document_id)
    assert isinstance(status, DocumentStatusResponse)
    assert status.status == "queued"
    assert status.analysis_run_ids == []
    assert status.files[0].file_document_id == created.file_document_id
    assert status.files[0].file_type == "pdf"
    with pytest.raises(AppError) as missing:
        _handler(router, "get_document_status")(uuid4())
    assert missing.value.code == "not_found"
    assert missing.value.http_status == 404


def test_verdict_readback_includes_scores_numeric_checks_and_anchor_provenance(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """Run endpoint returns exact numeric values and persisted evidence source details."""
    router, factory, settings, project_id = api_context
    document_id = uuid4()
    chunk = _source_chunk(document_id)
    claim = Claim(
        claim_id=uuid4(),
        document_id=document_id,
        claim_text="The model achieved 95% accuracy.",
        claim_type=ClaimType.QUANTITATIVE,
        source_anchor_id=chunk.anchor.anchor_id,
        char_start=0,
        char_end=len(chunk.text),
        extraction_method="test",
        extraction_confidence=0.9,
    )
    claim_id = derive_uuid(
        document_id,
        claim.source_anchor_id,
        claim.char_start,
        claim.char_end,
    )
    run_id = analysis_run_id(document_id, settings)
    evidence_id = derive_uuid(document_id, "evidence_chunk", chunk.chunk_id)
    numeric_check = NumericCheck(
        result=CheckResult.MATCH,
        claim_slots=NumericSlots(metric="accuracy", value=Decimal("0.950000000000000001")),
        evidence_slots=NumericSlots(metric="accuracy", value=Decimal("0.95")),
        tolerance=Decimal("0.000000000000000001"),
        difference=Decimal("0.000000000000000001"),
        validator_version="numeric-test-v1",
    )
    with factory() as session, session.begin():
        repository = PersistenceRepository(session)
        repository.create_document(
            document_id=document_id,
            project_id=project_id,
            filename="report.pdf",
            file_hash="f" * 64,
            storage_path="report.pdf",
            file_type="pdf",
        )
        repository.store_ingestion_result(document_id, IngestionResult(chunks=[chunk]))
        repository.store_claims([claim])
        repository.create_analysis_run(
            run_id=run_id,
            document_id=document_id,
            configuration={"retrieval_top_k": settings.retrieval_top_k},
            model_versions={"nli": "mock"},
            policy_version=POLICY_VERSION,
        )
        repository.store_numeric_verifications(
            run_id=run_id,
            claim_id=claim_id,
            results=[
                SlotVerification(
                    slot_index=0,
                    overall=CheckResult.MATCH,
                    reason="numeric_match",
                    per_evidence=[(chunk.chunk_id, numeric_check)],
                )
            ],
            evidence_persistence_ids=[evidence_id],
        )
        repository.store_nli_results(
            run_id=run_id,
            claim_id=claim_id,
            results=[
                PersistedNLIResult(
                    evidence_chunk_id=evidence_id,
                    classification=NLIClassification(NLILabel.ENTAILMENT, 0.01, 0.98, 0.01),
                )
            ],
            model_id="mock-nli",
            model_revision="mock-rev",
        )
        repository.store_reranker_results(
            run_id=run_id,
            claim_id=claim_id,
            results=[(evidence_id, 0.87)],
            model_id="mock-reranker",
            model_revision="mock-rev",
        )
        repository.store_verdict(
            run_id=run_id,
            claim_id=claim_id,
            verdict=Verdict(
                status=VerdictStatus.NEEDS_REVIEW,
                confidence=None,
                reason="threshold_unavailable:tau_ext",
                explanation=("Calibration threshold is unavailable.",),
            ),
            policy_version=POLICY_VERSION,
            evidence_persistence_ids=[evidence_id],
        )

    response = _handler(router, "get_analysis_run_verdicts")(run_id)
    assert isinstance(response, AnalysisRunVerdictsResponse)
    assert response.document_id == document_id
    verdict = response.verdicts[0]
    assert verdict.status == "Needs Review"
    assert verdict.reason == "threshold_unavailable:tau_ext"
    assert verdict.explanation == ["Calibration threshold is unavailable."]
    assert verdict.nli_results[0].entailment_score == 0.98
    assert verdict.reranker_results[0].score == 0.87
    check = verdict.numeric_verifications[0].checks[0]
    assert check.difference == "0.000000000000000001"
    assert check.claim_slots["value"] == "0.950000000000000001"
    source = verdict.evidence[0]
    assert source.evidence_chunk_id == evidence_id
    assert source.source_chunk_id == chunk.chunk_id
    assert source.anchor_id == chunk.anchor.anchor_id

    with pytest.raises(AppError) as missing:
        _handler(router, "get_analysis_run_verdicts")(uuid4())
    assert missing.value.code == "not_found"
    assert missing.value.http_status == 404


def test_upload_database_failure_removes_durable_file(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected persistence failures do not leave orphan files or expose details."""
    router, _factory, settings, project_id = api_context

    def fail_create_document(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private database information")

    monkeypatch.setattr(PersistenceRepository, "create_document", fail_create_document)
    with pytest.raises(RuntimeError, match="private database information"):
        _handler(router, "upload_document")(
            project_id,
            _upload("failure.pdf", b"%PDF-1.7\nfailure"),
            None,
        )
    assert list((settings.storage_root / str(project_id)).glob("*.pdf")) == []


def test_openapi_publishes_the_document_api_contract(
    api_context: tuple[APIRouter, sessionmaker[Session], Settings, UUID],
) -> None:
    """The app's OpenAPI document describes all added API operations and responses."""
    _router, factory, settings, _project_id = api_context
    schema = create_app(
        settings,
        database_check=lambda: True,
        session_factory=factory,
    ).openapi()
    paths = schema["paths"]

    upload_responses = paths["/api/v1/projects/{project_id}/documents"]["post"]["responses"]
    assert upload_responses.get("202")
    assert {"400", "404", "409", "413", "500", "503"} <= set(upload_responses)
    status_responses = paths["/api/v1/documents/{document_id}"]["get"]["responses"]
    assert {"200", "404", "500"} <= set(status_responses)
    verdict_responses = paths["/api/v1/analysis-runs/{run_id}/verdicts"]["get"]["responses"]
    assert {"200", "404", "500"} <= set(verdict_responses)
