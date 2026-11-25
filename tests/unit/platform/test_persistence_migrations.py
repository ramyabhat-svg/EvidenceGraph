"""Exercise the initial Alembic schema on an isolated SQLite database."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from eg_common.settings import get_settings


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path, monkeypatch) -> None:
    """Create and remove the full schema through the checked-in Alembic revision."""
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    try:
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_path}")
        database_inspector = inspect(engine)
        tables = set(database_inspector.get_table_names())
        assert {
            "projects",
            "documents",
            "source_locations",
            "evidence_chunks",
            "claims",
            "analysis_runs",
            "verification_results",
            "verification_evidence",
            "numeric_checks",
            "nli_results",
            "verdicts",
            "verdict_evidence",
            "reranker_results",
            "alembic_version",
        } <= tables
        evidence_columns = {
            column["name"] for column in inspect(engine).get_columns("evidence_chunks")
        }
        assert {
            "embedding",
            "embedding_model_id",
            "embedding_model_revision",
        } <= evidence_columns
        document_indexes = {index["name"] for index in database_inspector.get_indexes("documents")}
        assert "uq_documents_parent_csv" in document_indexes
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(f"sqlite:///{database_path}")
        assert inspect(engine).get_table_names() == ["alembic_version"]
        engine.dispose()
    finally:
        get_settings.cache_clear()
