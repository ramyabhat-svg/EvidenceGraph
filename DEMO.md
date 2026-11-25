# EvidenceGraph demo

## Run locally

Install the project's Python runtime and development requirements. In one terminal
at the repository root, run the demonstration API with disposable SQLite storage.

    python -m evaluation.demo --serve

In a second terminal, start the React app.

    npm.cmd ci --prefix apps/web
    npm.cmd run dev --prefix apps/web -- --host 127.0.0.1

Open the Vite address. Select **Methods reading group**, then **Held-out test
results**. Filter to **Needs Review** and open either claim. Inspect the source
anchor, numeric slots, and the verifier's trace. The CSV rows contain values,
but the demo verifier can abstain from a comparison when entity, metric or
period context does not align.

Record a review with a reviewer ID, a verdict and a rationale. Check that the
review appears immediately and that the system verdict remains visible.
Open **Analysis runs**, select the run to inspect its configuration, and open
both report formats. The policy and retrieval versions identify the fallback.
NLI is unavailable in this mode. The demo worker also processes new uploads
while the server is running. The native run inspector appears when the UI is
connected to the engineering API.

## Reproduce the smoke run

    python -m evaluation.demo --output evaluation/results/demo

The output directory contains the controlled PDF and CSV, the report, and the
CLI metrics. The generated labels are fixture expectations for this demonstration.
Research results require the human-annotated corpus and C's configured pipeline.

## Inspect Member C's runs

Start the combined stack from the repository root with `docker compose up --build`.
Open http://localhost:5173 and create a project. Upload a text-based PDF and,
optionally, a companion CSV. When processing finishes, open a claim, inspect
the evidence, record a review, and open the analysis run to export a report.
For the native verdict response, choose **Inspect a run** and enter its UUID.

Compose connects the UI to `/api/v1/workspace`. For local development against
the engineering API, set `VITE_API_BASE_URL=/api/v1/workspace` in the Vite
process environment. The SQLite walkthrough above uses the default `/api/v1`.
