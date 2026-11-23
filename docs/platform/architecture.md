# Platform architecture

EvidenceGraph runs as a modular monolith with separate API and worker processes. PostgreSQL
stores application state and provenance; the pgvector image provides the vector extension needed
by later retrieval work. The React web client is owned by Member D and is not part of this phase.

## Services

- **api** serves the FastAPI application under `/api/v1` and provides the `/health` alias used by
  local tooling.
- **worker** is a separate process. In Phase 0 it emits a startup event and idles until SIGTERM or
  SIGINT; job processing is added in a later phase.
- **postgres** runs PostgreSQL 16 with pgvector and is published only on the local loopback
  interface.
- **web** is the future React/Vite client owned by Member D.

The MVP has no user authentication. The Compose stack is for local development and is not
production-safe as deployed.

## Data flow

The intended pipeline is upload and file validation, PDF/CSV ingestion with source anchors, claim
extraction, evidence retrieval, semantic and numeric verification, verdict generation, provenance
persistence, and report delivery. Phase 0 implements only the runtime boundary, settings, database
connectivity health check, and process lifecycle. No domain or persistence models are introduced.

Uploaded files use a named volume mounted at the same storage path in the API and worker
containers. The database volume is separate. Both volumes are local Compose state.

## Ownership

Member A owns common platform utilities, API and persistence scaffolding, worker orchestration and
reporting, deployment, CI, and integration documentation. Member B owns ingestion, extraction,
numeric verification, and the scientific pack. Member C owns retrieval, NLI, and decision policy.
Member D owns evaluation and the web client. Cross-owner changes are recorded in
`docs/integration/requests-for-member-*.md` and implemented through A-owned adapters where
possible.
