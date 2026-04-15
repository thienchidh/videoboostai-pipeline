"""
db/config.py - Database configuration, engine, session, and init helpers.
"""
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from datetime import datetime, date, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from modules.pipeline.exceptions import MissingConfigError
import db_models as models

# Database connection config (updated by configure())
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "videopipeline",
    "user": "videopipeline",
    "password": "videopipeline123",
}

# SQLAlchemy engine + session factory (set by configure())
_engine = None
_SessionFactory = None


def configure(config: dict = None):
    """Configure database connection. Supports env var fallback."""
    global _engine, _SessionFactory

    if config is None:
        config = {}

    host = config.get("host") or os.getenv("POSTGRES_HOST", "localhost")
    port = config.get("port") or int(os.getenv("POSTGRES_PORT", "5432"))
    database = config.get("name") or config.get("database") or os.getenv("POSTGRES_DB", "videopipeline")
    user = config.get("user") or os.getenv("POSTGRES_USER", "videopipeline")
    password = config.get("password") or os.getenv("POSTGRES_PASSWORD", "videopipeline123")

    if not all([host, database, user]):
        raise MissingConfigError("database host, name, user are required")

    DB_CONFIG.update({
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
    })

    _engine = create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}",
        pool_size=1,
        max_overflow=10,
        pool_timeout=30,
        echo=False,
    )
    _SessionFactory = sessionmaker(bind=_engine)


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
