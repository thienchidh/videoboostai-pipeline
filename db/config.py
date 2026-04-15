"""
db/config.py - Database configuration, engine, session, and init helpers.
"""
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from datetime import datetime, date, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from modules.pipeline.db_config import DatabaseConnectionConfig
from modules.pipeline.exceptions import MissingConfigError
import db_models as models

# SQLAlchemy engine + session factory (set by configure())
_engine = None
_SessionFactory = None


def configure(config: DatabaseConnectionConfig):
    """Delegate to db.configure(). db.configure() now accepts DatabaseConnectionConfig directly."""
    import db as _db_module
    _db_module.configure(config)


def _ensure_configured():
    """Ensure configure() has been called before any DB operation."""
    if _SessionFactory is None:
        configure()


@contextmanager
def get_session() -> Session:
    """Context manager for SQLAlchemy sessions. Commits on success, rolls back on exception."""
    _ensure_configured()
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Alias for backward compatibility
get_db = get_session


def init_db():
    """Initialize database schema using SQLAlchemy models (creates all tables)."""
    _ensure_configured()
    models.Base.metadata.create_all(_engine)


def init_pgvector():
    """Enable pgvector extension. Must be called BEFORE init_db() to enable vector type."""
    _ensure_configured()
    from sqlalchemy import text
    with get_session() as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()


def init_db_full():
    """Init pgvector extension then create all tables."""
    init_pgvector()
    init_db()
