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
    "RETRIEVAL_TOP_K",
    "RETRIEVAL_BM25_K1",
    "RETRIEVAL_BM25_B",
    "RETRIEVAL_RRF_K",
    "EMBEDDING_BATCH_SIZE",
    "NLI_BATCH_SIZE",
    "RERANKER_BATCH_SIZE",
    "POLICY_TAU_EXT",
    "POLICY_TAU_RET",
    "POLICY_TAU_E",
    "POLICY_TAU_C",
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
    assert settings.retrieval_top_k == 20
    assert settings.retrieval_bm25_k1 == 1.5
    assert settings.retrieval_bm25_b == 0.75
    assert settings.retrieval_rrf_k == 60
    assert settings.embedding_batch_size == 32
    assert settings.nli_batch_size == 16
    assert settings.reranker_batch_size == 16
    assert settings.policy_tau_ext is None
    assert settings.policy_tau_ret is None
    assert settings.policy_tau_e is None
    assert settings.policy_tau_c is None


def test_retrieval_settings_are_configurable_and_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval parameters load from environment and reject invalid ranges."""
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_TOP_K", "7")
    monkeypatch.setenv("RETRIEVAL_BM25_K1", "1.2")
    monkeypatch.setenv("RETRIEVAL_BM25_B", "0.6")
    monkeypatch.setenv("RETRIEVAL_RRF_K", "45")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "5")
    monkeypatch.setenv("RERANKER_BATCH_SIZE", "3")

    settings = Settings(_env_file=None)

    assert settings.retrieval_top_k == 7
    assert settings.retrieval_bm25_k1 == 1.2
    assert settings.retrieval_bm25_b == 0.6
    assert settings.retrieval_rrf_k == 45
    assert settings.embedding_batch_size == 5
    assert settings.reranker_batch_size == 3
    with pytest.raises(ValueError):
        Settings(_env_file=None, retrieval_top_k=0)


def test_policy_thresholds_are_optional_and_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calibrated thresholds remain unset by default and load only when configured."""
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("POLICY_TAU_EXT", "0.65")
    monkeypatch.setenv("POLICY_TAU_RET", "0.42")
    monkeypatch.setenv("POLICY_TAU_E", "0.83")
    monkeypatch.setenv("POLICY_TAU_C", "0.79")

    settings = Settings(_env_file=None)

    assert settings.policy_tau_ext == 0.65
    assert settings.policy_tau_ret == 0.42
    assert settings.policy_tau_e == 0.83
    assert settings.policy_tau_c == 0.79
    with pytest.raises(ValueError):
        Settings(_env_file=None, policy_tau_e=1.1)


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
