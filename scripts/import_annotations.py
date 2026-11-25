"""Import human annotation JSONL without modifying system verdicts."""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from persistence.session import get_session_factory
from persistence.workflow import Annotation, Claim


class AnnotationInput(BaseModel):
    """Required human annotation fields, with additional research metadata preserved."""
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)
    annotation_id: str = Field(min_length=1)
    claim_id: UUID
    split: Literal["train", "dev", "test"]
    verdict: Literal[
        "Supported", "Partially Supported", "Contradicted", "Unsupported", "Needs Review"
    ]
    annotator_id: str = Field(min_length=1)
    annotation_date: date


def import_annotations(session: Session, path: Path, *, allow_test: bool = False) -> int:
    """Validate and upsert all records into the caller's transaction."""
    if path.stem.casefold() == "test" and not allow_test:
        raise ValueError("Use --allow-test only for the authorized final evaluation.")
    count = 0
    with path.open(encoding="utf-8") as records:
        for line_number, line in enumerate(records, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if isinstance(raw, dict) and raw.get("split") == "test" and not allow_test:
                    raise ValueError("Test import requires --allow-test.")
                annotation = AnnotationInput.model_validate(raw)
                claim_id = str(annotation.claim_id)
                if session.get(Claim, claim_id) is None:
                    raise ValueError("Claim ID was not found. Process the document first.")
            except ValueError as exc:
                raise ValueError(f"Annotation import failed at line {line_number}.") from exc
            session.merge(Annotation(
                id=annotation.annotation_id, claim_id=claim_id,
                data=annotation.model_dump(mode="json"),
            ))
            count += 1
    return count


def main() -> None:
    """Import an explicitly selected annotation dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--allow-test", action="store_true")
    arguments = parser.parse_args()
    with get_session_factory().begin() as session:
        count = import_annotations(session, arguments.path, allow_test=arguments.allow_test)
    print(f"Imported {count} annotations.")


if __name__ == "__main__":
    main()
