"""SQLite 增量结构升级（D-51）。

新库由 create_all 建表；已有 SQLite 库补齐缺失列与头像待审事项。
审计清理按现行规则删除匿名事件，保留账户及明确系统任务记录。
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

# 仅允许追加、可空、无服务端默认值的列；升级可重复执行。
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "disposal_cases": {"avatar_key": "VARCHAR(512)"},
    "users": {'avatar_key': 'VARCHAR(512)', 'avatar_pending_key': 'VARCHAR(512)', 'avatar_review_status': 'VARCHAR(16)', 'avatar_review_reason': 'VARCHAR(500)'},
    "trades": {
        "confirm_wait_paused_at": "DATETIME",
        "confirm_wait_remaining_seconds": "INTEGER",
    },
    # 任务 K：旧本地 SQLite 库只追加标签审核原因列，不重建、不丢历史申请。
    "product_tag_applications": {
        "decision_reason": "VARCHAR(500)",
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
    if {'users', 'disposal_cases'} <= existing_tables:
        conn.execute(text("""INSERT INTO disposal_cases
            (case_type, status, subject_user_id, title, avatar_key)
            SELECT 'avatar_review', 'pending', users.id, '头像审核', users.avatar_pending_key
            FROM users WHERE users.avatar_review_status='pending'
            AND users.avatar_pending_key IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM disposal_cases c
                WHERE c.case_type='avatar_review' AND c.subject_user_id=users.id
                AND c.status IN ('pending','processing'))"""))
    if 'audit_events' in existing_tables:
        conn.execute(text("DELETE FROM audit_events WHERE actor_role='anonymous' OR (actor_id IS NULL AND actor_role<>'system')"))
    return applied
