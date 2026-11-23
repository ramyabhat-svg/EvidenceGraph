"""Structured JSON logging with a restricted field allowlist."""

import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALLOWED_FIELDS = {
    "project_id",
    "document_id",
    "run_id",
    "job_id",
    "count",
    "duration_ms",
    "error_code",
}


class JsonFormatter(logging.Formatter):
    """Format records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log event without rendering arbitrary record extras."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event_name", "unstructured_log_suppressed"),
        }
        for field in _ALLOWED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value) if isinstance(value, UUID) else value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a JSON stream handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    project_id: UUID | str | None = None,
    document_id: UUID | str | None = None,
    run_id: UUID | str | None = None,
    job_id: UUID | str | None = None,
    count: int | None = None,
    duration_ms: float | None = None,
    error_code: str | None = None,
    level: int = logging.INFO,
) -> None:
    """Log an event using only ID, count, duration, and error-code fields."""
    if not _EVENT_PATTERN.fullmatch(event):
        raise ValueError("event must be a lowercase snake_case identifier")
    for identifier in (project_id, document_id, run_id, job_id):
        if identifier is not None:
            try:
                UUID(str(identifier))
            except ValueError as exc:
                raise ValueError("identifier fields must contain UUIDs") from exc
    if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
        raise TypeError("count must be an integer")
    if count is not None and count < 0:
        raise ValueError("count must be non-negative")
    if duration_ms is not None and not math.isfinite(duration_ms):
        raise ValueError("duration_ms must be finite")
    if duration_ms is not None and duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if error_code is not None and not _EVENT_PATTERN.fullmatch(error_code):
        raise ValueError("error_code must be a lowercase snake_case identifier")
    fields = {
        key: value
        for key, value in locals().items()
        if key in _ALLOWED_FIELDS and value is not None
    }
    logger.log(level, event, extra={"event_name": event, **fields})
