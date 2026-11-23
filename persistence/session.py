"""Lazy SQLAlchemy engine and session factory configuration."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from eg_common.settings import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process-wide engine on first use without connecting eagerly."""
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return a process-wide SQLAlchemy 2.0 session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def database_is_available() -> bool:
    """Return whether a lightweight database query succeeds."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
