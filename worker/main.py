"""Minimal worker process lifecycle for the platform skeleton."""

import logging
import signal
import threading

from eg_common.logging import configure_logging, log_event
from eg_common.settings import get_settings
from persistence.session import get_session_factory
from worker.orchestration.ingestion import process_next_document


def main() -> None:
    """Log startup, idle until shutdown, and exit cleanly on termination signals."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("evidencegraph.worker")
    stop_event = threading.Event()

    def request_shutdown(_signal_number: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    log_event(logger, "worker_started")
    while not stop_event.wait(timeout=settings.worker_poll_seconds):
        try:
            process_next_document(get_session_factory())
        except Exception:
            log_event(
                logger,
                "document_processing_failed",
                error_code="worker_processing_failed",
                level=logging.ERROR,
            )
    log_event(logger, "worker_stopped")


if __name__ == "__main__":
    main()
