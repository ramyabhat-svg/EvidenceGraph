# Review workspace integration

The combined service supports two local workflows.

- The engineering workspace uses PostgreSQL, pgvector and Member C’s pipeline.
  Start it with `docker compose up --build` and open http://localhost:5173.
  The React screens read and write through `/api/v1/workspace`. Native API
  clients continue to use the engineering endpoints under `/api/v1`.
- The seeded SQLite demonstration runs with `python -m evaluation.demo --serve`.
  It uses Member B’s parser and numeric checks with a fallback retrieval and
  decision policy. See [the walkthrough](../../DEMO.md) for the frontend command.

Alembic manages the engineering database. Migration 0006 adds project and
document display metadata and review history. The review is tied to the
persisted system verdict. Editing the review decision leaves the original run
available for inspection. The SQLite schema and annotation importer belong to
the demonstration workflow.

See [the evaluation guide](../../evaluation/README.md) for the real-data pilots,
review protocol and experiment runner.
