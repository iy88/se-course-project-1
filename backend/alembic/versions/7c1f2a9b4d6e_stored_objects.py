"""stored objects registry

Revision ID: 7c1f2a9b4d6e
Revises: d98486eb9bb0
Create Date: 2026-10-30 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7c1f2a9b4d6e"
down_revision: str | None = "d98486eb9bb0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("namespace", sa.String(length=32), nullable=False),
        sa.Column("bucket_role", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "object_metadata",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('staged', 'committed', 'deleted')",
            name=op.f("ck_stored_objects_state_allowed"),
        ),
        sa.CheckConstraint(
            "bucket_role IN ('media', 'evidence')",
            name=op.f("ck_stored_objects_bucket_role_allowed"),
        ),
        sa.CheckConstraint(
            "(ref_type IS NULL) = (ref_id IS NULL)",
            name=op.f("ck_stored_objects_reference_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_stored_objects_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_stored_objects")),
    )
    op.create_index(
        op.f("ix_stored_objects_namespace"), "stored_objects", ["namespace"], unique=False
    )
    op.create_index(
        op.f("ix_stored_objects_owner_id"), "stored_objects", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_stored_objects_state"), "stored_objects", ["state"], unique=False
    )
    op.create_index(
        "ix_stored_objects_state_created_at",
        "stored_objects",
        ["state", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_stored_objects_ref",
        "stored_objects",
        ["ref_type", "ref_id"],
        unique=False,
    )
    if op.get_context().dialect.name == "postgresql":
        role = op.get_context().config.attributes.get("migration_app_role")
        schema = op.get_context().config.attributes["migration_schema"]
        if not role:
            raise RuntimeError("migration app role is required to grant registry privileges")
        # app 只能登记/提交/标记回收，不能删除登记或清空表。
        op.execute(sa.text(f'REVOKE ALL ON "{schema}".stored_objects FROM PUBLIC'))
        op.execute(
            sa.text(f'REVOKE DELETE, TRUNCATE ON "{schema}".stored_objects FROM "{role}"')
        )
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE ON "{schema}".stored_objects TO "{role}"')
        )


def downgrade() -> None:
    op.drop_index("ix_stored_objects_ref", table_name="stored_objects")
    op.drop_index("ix_stored_objects_state_created_at", table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_state"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_owner_id"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_namespace"), table_name="stored_objects")
    op.drop_table("stored_objects")
