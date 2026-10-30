"""数据库方言兼容类型：SQLite 使用 JSON，PostgreSQL 使用 JSONB。"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSON().with_variant(JSONB(), "postgresql")
