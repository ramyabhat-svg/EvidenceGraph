"""Structured logging safety tests."""

import json
import logging
from uuid import uuid4

import pytest

from eg_common.logging import JsonFormatter, log_event


def test_logging_helper_emits_only_allowed_fields() -> None:
    """The JSON record includes allowed identifiers and numeric metadata."""
    logger = logging.getLogger("test.platform.logging")
    logger.setLevel(logging.INFO)
    records: list[logging.LogRecord] = []

    class RecordHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = RecordHandler()
    logger.addHandler(handler)
    log_event(logger, "worker_started", document_id=uuid4(), count=3, duration_ms=1.5)
    logger.removeHandler(handler)

    payload = json.loads(JsonFormatter().format(records[0]))
    assert payload["event"] == "worker_started"
    assert payload["count"] == 3
    assert payload["duration_ms"] == 1.5
    assert "document_id" in payload
    with pytest.raises(TypeError):
        log_event(logger, "document_processed", **{"document_text": "private text"})


def test_json_formatter_does_not_render_unapproved_record_extras() -> None:
    """Arbitrary extra data cannot leak through the formatter."""
    logger = logging.getLogger("test.platform.logging.safety")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "private document text",
        (),
        None,
        extra={"document_text": "private text", "count": 2},
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["count"] == 2
    assert "document_text" not in payload
    assert payload["event"] == "unstructured_log_suppressed"


def test_configure_logging_installs_the_json_formatter() -> None:
    """Root logging is configured with the JSON formatter and requested level."""
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    try:
        from eg_common.logging import configure_logging

        configure_logging("DEBUG")

        assert root_logger.level == logging.DEBUG
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0].formatter, JsonFormatter)
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
