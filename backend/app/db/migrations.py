"""SQLite 增量结构升级（D-51）。

新库由 create_all 正常建表；已有 SQLite 库只追加缺失列，不删除/重建表，不丢数据。
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

# 仅允许追加、可空、无服务端默认值的列；升级可重复执行。
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "trades": {
        "confirm_wait_paused_at": "DATETIME",
        "confirm_wait_remaining_seconds": "INTEGER",
    },
}


def upgrade_additive_schema(conn: Connection) -> list[str]:
    """在 create_all 之后补齐旧库缺失列，返回实际追加的列名。"""
    if conn.dialect.name != "sqlite":
        return []
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []
    for table, columns in ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl_type in columns.items():
            if name in existing_columns:
                continue
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl_type}'))
            applied.append(f"{table}.{name}")
    return applied
