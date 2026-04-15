"""
modules/pipeline/db_config.py — Pydantic model for database connection configuration.

Replaces the old DB_CONFIG dict in db.py.
"""
from pydantic import BaseModel


class DatabaseConnectionConfig(BaseModel):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str
