"""Typed application settings loaded from unprefixed environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by the API, worker, and persistence layer."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        enable_decoding=False,
        extra="ignore",
        validate_default=True,
    )

    database_url: str = "postgresql://evidencegraph:evidencegraph@localhost:5432/evidencegraph"
    cors_origins: list[str] = ["http://localhost:5173"]
    api_port: int = 8000
    stub_mode: bool = False
    evidencegraph_env: Literal["development", "evaluation", "production"] = "development"
    log_level: str = "INFO"
    storage_root: Path = Path("storage")
    max_pdf_mb: int = 50
    max_csv_mb: int = 5
    max_pdf_pages: int = 200
    job_max_attempts: int = 3
    job_backoff_base_seconds: int = 30
    job_lock_timeout_seconds: int = 900
    worker_poll_seconds: int = 2

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Select psycopg 3 for plain PostgreSQL URLs."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        """Parse comma-separated origins while retaining list input support."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
