"""Persistence session construction and health query tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

import persistence.session as session_module
from eg_common.settings import Settings


def test_engine_is_created_lazily_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing persistence has no engine side effects; first access creates one."""
    session_module.get_engine.cache_clear()
    calls: list[tuple[str, bool]] = []
    engine = object()

    def fake_create_engine(database_url: str, *, pool_pre_ping: bool) -> object:
        calls.append((database_url, pool_pre_ping))
        return engine

    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: Settings(database_url="postgresql+psycopg://local/test", _env_file=None),
    )
    monkeypatch.setattr(session_module, "create_engine", fake_create_engine)

    assert calls == []
    assert session_module.get_engine() is engine
    assert calls == [("postgresql+psycopg://local/test", True)]
    session_module.get_engine.cache_clear()


def test_session_factory_uses_lazy_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session factory binds the engine and disables commit expiration."""
    session_module.get_session_factory.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(session_module, "get_engine", lambda: engine)

    factory = session_module.get_session_factory()
    with factory() as session:
        assert session.is_active
    assert factory.kw["expire_on_commit"] is False
    session_module.get_session_factory.cache_clear()
    engine.dispose()


def test_database_health_returns_false_for_sqlalchemy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SQLAlchemy connectivity error becomes a false readiness result."""

    class FailingConnection:
        def __enter__(self) -> "FailingConnection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _statement: object) -> None:
            raise SQLAlchemyError("database unavailable")

    class FailingEngine:
        def connect(self) -> FailingConnection:
            return FailingConnection()

    monkeypatch.setattr(session_module, "get_engine", FailingEngine)

    assert session_module.database_is_available() is False


def test_database_health_runs_a_simple_select(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful SELECT 1 marks database readiness as available."""
    statements: list[str] = []

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            statements.append(str(statement))

    class Engine:
        def connect(self) -> Connection:
            return Connection()

    monkeypatch.setattr(session_module, "get_engine", Engine)

    assert session_module.database_is_available() is True
    assert statements == ["SELECT 1"]
