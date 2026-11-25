"""Export captured policy inputs for one explicitly selected dev run."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.models import AnalysisRunRow, DocumentRow, VerdictRow
from persistence.session import get_session_factory


def export_dev_inputs(session: Session, run_id: UUID) -> list[dict[str, object]]:
    """Read a complete snapshot for a run; reject historical or partial captures."""
    run = session.get(AnalysisRunRow, run_id)
    if run is None:
        raise ValueError("Unknown analysis run.")
    document = session.get(DocumentRow, run.document_id)
    if document is None or document.status != "complete":
        raise ValueError("The run's document must be complete.")
    verdicts = session.scalars(
        select(VerdictRow).where(VerdictRow.run_id == run_id).order_by(VerdictRow.claim_id)
    ).all()
    if not verdicts or any(row.policy_inputs is None for row in verdicts):
        raise ValueError("Run has no complete policy input capture; use a fresh engineering run.")
    return [
        {
            **row.policy_inputs,
            "claim_id": str(row.claim_id),
            "document_id": str(document.id),
            "pdf_sha256": document.file_hash,
            "analysis_run_id": str(run_id),
            "policy_version": row.policy_version,
            "split": "dev",
        }
        for row in verdicts
        if row.policy_inputs is not None
    ]


def main() -> None:
    """Export a run whose document is assigned to the development split."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-run-id", required=True, type=UUID)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with get_session_factory()() as session:
        rows = export_dev_inputs(session, args.dev_run_id)
    with args.output.open("x", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
