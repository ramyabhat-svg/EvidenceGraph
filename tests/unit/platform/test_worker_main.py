"""Worker process lifecycle tests."""

import signal

import pytest

import worker.main as worker_main
from eg_common.settings import Settings


def test_worker_logs_start_and_stop_and_registers_shutdown_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker startup and graceful signal shutdown do not perform real sleeps."""
    events: list[str] = []
    signals: list[int] = []

    class ImmediateStopEvent:
        def wait(self, timeout: float | None = None) -> bool:
            assert timeout == 7
            return True

    monkeypatch.setattr(worker_main, "get_settings", lambda: Settings(worker_poll_seconds=7))
    monkeypatch.setattr(worker_main, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        worker_main,
        "log_event",
        lambda _logger, event: events.append(event),
    )
    monkeypatch.setattr(worker_main.threading, "Event", ImmediateStopEvent)
    monkeypatch.setattr(
        worker_main.signal,
        "signal",
        lambda signal_number, _handler: signals.append(signal_number),
    )

    worker_main.main()

    assert events == ["worker_started", "worker_stopped"]
    assert signals == [signal.SIGTERM, signal.SIGINT]
