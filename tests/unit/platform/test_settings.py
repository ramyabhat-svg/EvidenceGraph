"""Settings defaults and environment parsing tests."""

import pytest

from eg_common.settings import Settings

_ENVIRONMENT_FIELDS = (
    "DATABASE_URL",
    "CORS_ORIGINS",
    "API_PORT",
    "STUB_MODE",
    "EVIDENCEGRAPH_ENV",
    "LOG_LEVEL",
    "STORAGE_ROOT",
    "MAX_PDF_MB",
    "MAX_CSV_MB",
    "MAX_PDF_PAGES",
    "JOB_MAX_ATTEMPTS",
    "JOB_BACKOFF_BASE_SECONDS",
    "JOB_LOCK_TIMEOUT_SECONDS",
    "WORKER_POLL_SECONDS",
)


def _clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient settings so each test controls its own inputs."""
    for field in _ENVIRONMENT_FIELDS:
        monkeypatch.delenv(field, raising=False)


def test_settings_defaults_and_database_url_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defaults use the platform values and select the psycopg driver."""
    _clear_settings_environment(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.database_url == (
        "postgresql+psycopg://evidencegraph:evidencegraph@localhost:5432/evidencegraph"
    )
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.api_port == 8000
    assert settings.stub_mode is False
    assert settings.evidencegraph_env == "development"
    assert settings.log_level == "INFO"
    assert settings.storage_root.as_posix() == "storage"
    assert settings.max_pdf_mb == 50
    assert settings.max_csv_mb == 5
    assert settings.max_pdf_pages == 200
    assert settings.job_max_attempts == 3
    assert settings.job_backoff_base_seconds == 30
    assert settings.job_lock_timeout_seconds == 900
    assert settings.worker_poll_seconds == 2


def test_settings_use_unprefixed_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Uppercase environment variables map to lowercase settings fields."""
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db:5432/graph")
    monkeypatch.setenv("API_PORT", "8123")
    monkeypatch.setenv("STUB_MODE", "true")
    monkeypatch.setenv("EVIDENCEGRAPH_ENV", "evaluation")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://user:pass@db:5432/graph"
    assert settings.api_port == 8123
    assert settings.stub_mode is True
    assert settings.evidencegraph_env == "evaluation"


def test_cors_origins_parse_comma_separated_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORS_ORIGINS is exposed as trimmed origins without empty entries."""
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, http://localhost:5173,,")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["https://one.example", "http://localhost:5173"]
