"""Minimal worker process lifecycle for the platform skeleton."""

import logging
import signal
import threading

from eg_common.logging import configure_logging, log_event
from eg_common.settings import get_settings


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
        pass
    log_event(logger, "worker_stopped")


if __name__ == "__main__":
    main()
