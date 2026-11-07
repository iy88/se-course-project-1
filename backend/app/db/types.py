"""Dialect-compatible database types: JSON for SQLite and JSONB for PostgreSQL."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSON().with_variant(JSONB(), "postgresql")
