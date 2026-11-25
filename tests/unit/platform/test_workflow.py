"""Exercise the handoff across upload, analysis, review, and export."""

import json
from io import BytesIO

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api import workflow
from apps.api.demo_app import create_app
from eg_common.settings import Settings
from persistence.workflow import Annotation, Base, GraphEdge
from scripts.import_annotations import import_annotations
from worker.orchestration.workflow import process_next


def test_document_workflow(tmp_path, monkeypatch) -> None:
    """An uploaded PDF reaches an immutable trace, with separate human reviews."""
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(workflow, "get_session_factory", lambda: factory)
    settings = Settings(storage_root=tmp_path / "uploads")
    client = TestClient(create_app(settings, database_check=lambda: True))
    project = client.post("/api/v1/projects", json={"name": "Review"}).json()
    project_id = project["project_id"]
    assert client.get("/api/v1/projects").json()["total"] == 1
    path = f"/api/v1/projects/{project_id}/documents"
    buffer = BytesIO()
    pdf = Canvas(buffer)
    pdf.drawString(60, 700, "Model A achieves 91% accuracy.")
    pdf.drawString(60, 670, "Model B achieves 89% recall.")
    pdf.save()
    files = {"pdf_file": ("paper.pdf", buffer.getvalue()),
             "csv_file": ("values.csv", b"Model,Accuracy\nModel A,91%\n")}
    response = client.post(path, files=files)
    assert response.status_code == 202, response.text
    assert client.post(path, files=files).status_code == 409
    assert len(list(settings.storage_root.iterdir())) == 2
    document_id = response.json()["document_id"]
    document_url = f"/api/v1/documents/{document_id}"
    assert client.get(document_url).json()["status"] == "queued"
    assert process_next(factory, settings)
    assert client.get(document_url).json()["status"] == "complete"
    claims_url = f"{document_url}/claims"
    result = client.get(claims_url, params={"status": "Needs Review", "page_size": 1}).json()
    assert result["total"] == 2
    assert len(result["claims"]) == 1
    assert client.get(claims_url, params={"status": "Processing Error"}).status_code == 400
    claim_id = result["claims"][0]["claim_id"]
    claim_url = f"/api/v1/claims/{claim_id}"
    trace = client.get(claim_url).json()
    assert isinstance(trace["numeric_slots"][0]["value"], str)
    assert any(item["source_anchor"]["page"] is None for item in trace["retrieved_evidence"])
    assert trace["nli_results"] == []
    run_id = trace["verdict"]["run_id"]
    review = client.post(f"{claim_url}/reviews", json={
        "reviewer_id": "D", "override_verdict": "Supported",
        "note": "Reviewed <b>evidence</b>.", "flag_for_rerun": True,
    })
    assert review.status_code == 201, review.text
    trace = client.get(claim_url).json()
    assert trace["verdict"]["verdict_status"] == "Needs Review"
    assert trace["review_history"][0]["override_verdict"] == "Supported"
    with factory() as session:
        assert session.scalar(select(GraphEdge)).edge_type == "CLAIM_REVIEWED_BY"
    report_url = f"/api/v1/runs/{run_id}/report"
    assert client.get(report_url).json()["summary"]["total_claims"] == 2
    html = client.get(report_url, params={"format": "html"}).text
    assert "&lt;b&gt;evidence&lt;/b&gt;" in html
    assert client.post(f"{document_url}/analyze").status_code == 202
    assert process_next(factory, settings)
    assert client.get(claim_url).json()["verdict"]["run_id"] != run_id
    assert client.get(report_url).json()["claims"][0]["claim_id"] == claim_id

    annotations = tmp_path / "dev.jsonl"
    record = {"annotation_id": "ann-test-fixture", "claim_id": claim_id, "split": "dev",
              "verdict": "Supported", "annotator_id": "D", "annotation_date": "2026-01-01"}
    annotations.write_text(json.dumps(record), encoding="utf-8")
    with factory.begin() as session:
        assert import_annotations(session, annotations) == 1
    record["verdict"] = "Contradicted"
    annotations.write_text(json.dumps(record), encoding="utf-8")
    with factory.begin() as session:
        assert import_annotations(session, annotations) == 1
    with factory() as session:
        assert session.scalar(select(Annotation)).data["verdict"] == "Contradicted"
    assert client.get(claim_url).json()["verdict"]["verdict_status"] == "Needs Review"
