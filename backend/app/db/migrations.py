"""SQLite incremental schema upgrades (D-51).

New databases are created by create_all; existing SQLite databases get missing
columns plus pending avatar review cases. Audit cleanup deletes anonymous events
per current rules while retaining accounts and explicit system task records.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

# Only additive, nullable columns without server defaults are allowed; the upgrade is idempotent.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "disposal_cases": {"avatar_key": "VARCHAR(512)"},
    "users": {'avatar_key': 'VARCHAR(512)', 'avatar_pending_key': 'VARCHAR(512)', 'avatar_review_status': 'VARCHAR(16)', 'avatar_review_reason': 'VARCHAR(500)'},
    "trades": {
        "confirm_wait_paused_at": "DATETIME",
        "confirm_wait_remaining_seconds": "INTEGER",
    },
    # Task K: old local SQLite databases only get the tag review reason column; no rebuild and no loss of historical applications.
    "product_tag_applications": {
        "decision_reason": "VARCHAR(500)",
    },
}


def upgrade_additive_schema(conn: Connection) -> list[str]:
    """Add missing columns to an old database after create_all and return the columns actually added."""
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


def drop_upload_size_constraint(conn: Connection) -> None:
    """Preserve old SQLite leases while removing the fixed upload size constraint."""
    if conn.dialect.name != "sqlite" or "upload_leases" not in inspect(conn).get_table_names():
        return
    constraints = inspect(conn).get_check_constraints("upload_leases")
    old = next((item for item in constraints if "size_bytes" in item["sqltext"]), None)
    if old is None:
        return
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    operations = Operations(MigrationContext.configure(conn))
    with operations.batch_alter_table("upload_leases") as batch:
        batch.drop_constraint(old["name"], type_="check")
