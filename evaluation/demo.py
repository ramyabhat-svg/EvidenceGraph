"""Generate controlled review inputs and exercise the real A/B pipeline."""

import argparse
import json
import logging
import os
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas


def demo_pdf():
    """Build a small reproducible text-based PDF for a smoke test."""
    data = BytesIO()
    pdf = Canvas(data, invariant=1)
    pdf.setTitle("Accuracy and recall on a held-out test set")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(56, 720, "Held-out test results")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(56, 674, "Model A achieves 91% accuracy on the test set.")
    pdf.drawString(56, 644, "Model B achieves 89% recall on the test set.")
    pdf.save()
    return data.getvalue()


DEMO_CSV = b"Model,Accuracy,Recall\nModel A,91%,82%\nModel B,85%,89%\n"


def smoke(directory, serve, port=8000):
    """Upload PDF/CSV, run extraction and checks, and exercise the evaluation CLI."""
    from apps.api.demo_app import create_app
    from eg_common.settings import get_settings
    from evaluation.run_eval import main as run_eval
    from persistence.session import get_engine, get_session_factory
    from persistence.workflow import Base
    from worker.orchestration.workflow import process_next

    Base.metadata.create_all(get_engine())
    settings = get_settings()
    app = create_app(settings)
    with TestClient(app) as client:
        def unpack(response):
            response.raise_for_status()
            return response.json()

        project = unpack(client.post("/api/v1/projects", json={"name": "Methods reading group"}))
        project_id = project["project_id"]
        unpack(client.post(
            f"/api/v1/projects/{project_id}/documents",
            files={"pdf_file": ("demo.pdf", demo_pdf()), "csv_file": ("demo.csv", DEMO_CSV)},
            data={"document_name": "Held-out test results"},
        ))
        if not process_next(get_session_factory(), settings):
            raise RuntimeError("Demo analysis was not queued.")
        runs = unpack(client.get(f"/api/v1/projects/{project_id}/runs"))
        run = runs["runs"][0]
        report = unpack(client.get(f"/api/v1/runs/{run['run_id']}/report"))
        if len(report["claims"]) != 2 or not any(
            claim["numeric_checks"] for claim in report["claims"]
        ):
            raise RuntimeError("Expected two extracted claims and numeric verification records.")

    report_path = directory / "fallback-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    annotations = directory / "fixture.jsonl"
    with annotations.open("w", encoding="utf-8") as destination:
        for index, claim in enumerate(report["claims"]):
            # Structural smoke-test expectations only. These are not research ground truth.
            fixture = {"annotation_id": f"fixture-{index}", "paper_id": "controlled-demo",
                       "claim_id": claim["claim_id"], "split": "dev", "verdict": "Needs Review"}
            destination.write(json.dumps(fixture) + "\n")
    import sys
    sys.argv = ["run_eval", "--experiment", "full_system", "--split", "dev", "--annotations",
                str(annotations), "--report", str(report_path), "--allow-fallback", "--output",
                str(directory / "smoke-metrics.json")]
    run_eval()
    print(f"Extracted {len(report['claims'])} claims with real B numeric checks.")
    if serve:
        import uvicorn
        stop = Event()

        def consume_queue():
            """Process subsequent uploads until the demo server shuts down."""
            factory = get_session_factory()
            while not stop.wait(0.5):
                try:
                    process_next(factory, settings)
                except Exception:
                    logging.getLogger(__name__).error("Demo queue worker error")

        worker = Thread(target=consume_queue, name="demo-worker")
        worker.start()
        try:
            uvicorn.run(app, host="127.0.0.1", port=port)
        finally:
            stop.set()
            worker.join()


def main():
    """Run the demonstration in disposable storage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--serve", action="store_true", help="Serve the seeded API locally.")
    parser.add_argument("--output", type=Path, help="Keep inputs and results in a new directory.")
    args = parser.parse_args()

    def run(directory):
        os.environ["DATABASE_URL"] = f"sqlite:///{directory.joinpath('demo.sqlite').as_posix()}"
        os.environ["STORAGE_ROOT"] = str(directory / "uploads")
        (directory / "demo.pdf").write_bytes(demo_pdf())
        (directory / "demo.csv").write_bytes(DEMO_CSV)
        from persistence.session import get_engine

        try:
            smoke(directory, args.serve, args.port)
        finally:
            get_engine().dispose()

    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        run(args.output.resolve())
    else:
        with TemporaryDirectory() as directory:
            run(Path(directory))


if __name__ == "__main__":
    main()

